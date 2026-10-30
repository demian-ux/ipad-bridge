"""Puente entre el servidor (WebSocket) y la app nativa del iPad (TCP por USB vía usbmux, o por IP).

Se conecta al servidor como un visor más ("ipad"), así que la página de la PC no cambia:
recibe vconfig + frames HEVC y los reenvía a la app con el framing u32 largo + u8 tipo.
Los eventos del Pencil vuelven por el mismo socket y se entregan al servidor como input.
Corre en la misma PC que el servidor, por eso el servidor lo acepta sin código de emparejamiento: por USB el cable
es la autorización; por IP la escribió el dueño de la PC, o la pidió la app con el código (/connect, ver abajo).

Transporte en caliente ("el cable manda"): mientras la sesión va por red vigila usbmux cada 2 s y, si aparece el
iPad por USB, abre la conexión por el cable; cuando la app la acepta migra la sesión a ella (la conexión con el servidor
es la misma), cierra la de red y manda {"type":"transport","transport":"usb"}: el servidor reinicia la captura con el
bitrate de USB y el corte es un keyframe. Si se desenchufa el cable la sesión termina y se vuelve a conectar: por USB
si vuelve el cable, si no por red a la IP de respaldo (la de la línea de comandos o la que pidió la app por /connect).

Liveness: latido (tipo 0) cada 2 s hacia la app, que lo devuelve (la app vieja no: a esa no se la corta por silencio);
5 s sin bytes de la app cortan la sesión. Con el servidor lo mismo: ping/pong JSON cada 2 s (tag "bridge", para no
confundirlos con los de la app), 5 s sin nada = servidor caído. Reintentos con espera creciente (2 → 10 s).

Uso:
  python usb_bridge.py                 # USB: primer iPad conectado (requiere "Dispositivos Apple" o iTunes instalado)
  python usb_bridge.py 192.168.1.63    # por red: IP del iPad (cable Ethernet o Wi-Fi), sin usbmux
  python usb_bridge.py usb ws://localhost/ws
  python usb_bridge.py auto ws://localhost/ws 192.168.1.63   # USB si está disponible, si no por red (respaldo)
  python usb_bridge.py auto ws://localhost/ws                # USB, o la IP que la app pida al servidor (/connect)
Pruebas sin iPad: IPADBRIDGE_FAKE_USB=7778 hace que "USB" sea una conexión TCP a 127.0.0.1:7778 (tools/fake_app.py).
"""
import asyncio
import base64
import inspect
import json
import os
import socket
import struct
import sys
import time

import aiohttp

APP_PORT = 7777
T_PING, T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY = 0, 1, 2, 3, 4, 16, 17
T_CTRL_UP, T_CTRL_DOWN = 18, 19      # JSON de control tal cual va por el WebSocket (ver abajo qué tipos pasan)
CTRL_UP_TYPES = {"ping", "stats", "quality", "need-key", "sleeping", "wake", "closing"}   # iPad -> servidor
CTRL_DOWN_TYPES = {"pong", "welcome", "auth", "transport", "app"}                          # servidor -> iPad
LIVENESS = 5.0
USB_POLL = 2.0
FAKE_USB = int(os.environ.get("IPADBRIDGE_FAKE_USB", "0") or 0)


def frame(t, payload):
    return struct.pack(">IB", 1 + len(payload), t) + payload


def log(msg):
    print(f"[usb] {time.strftime('%H:%M:%S')} {msg}", flush=True)


async def usb_device():
    """iPad visible por USB vía el servicio de Apple (app 'Dispositivos Apple' o iTunes), o None."""
    try:
        from pymobiledevice3 import usbmux
        dev = usbmux.select_device(connection_type="USB")
        if inspect.isawaitable(dev):
            dev = await dev
        return dev
    except Exception as e:  # usbmuxd ausente, sin dispositivos, etc.
        log(f"usbmux: {type(e).__name__}: {e}")
        return None


class Link:
    """Una conexión TCP con la app del iPad, por USB ("usb") o por IP ("net")."""

    def __init__(self, reader, writer, transport, where=""):
        self.reader, self.writer, self.transport, self.where = reader, writer, transport, where
        self.last_rx = time.monotonic()
        self.echoes = False        # la app devuelve el latido: recién entonces se aplica el corte por silencio
        sock = writer.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass

    async def read(self):
        head = await self.reader.readexactly(5)
        length, t = struct.unpack(">IB", head)
        body = await self.reader.readexactly(length - 1)
        self.last_rx = time.monotonic()
        return t, body

    def write(self, data):
        self.writer.write(data)

    async def drain(self):
        await self.writer.drain()

    def close(self):
        try:
            self.writer.close()
        except Exception:
            pass


async def open_usb():
    """Conexión al puerto de la app a través del cable (usbmux). None si no hay iPad por USB."""
    if FAKE_USB:   # prueba sin iPad: el "cable" es una conexión local a tools/fake_app.py en ese puerto
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", FAKE_USB), 2)
        except (OSError, asyncio.TimeoutError):
            return None
        return Link(r, w, "usb", f"fake-usb:{FAKE_USB}")
    dev = await usb_device()
    if dev is None:
        return None
    log(f"iPad {dev.serial} por USB, abriendo puerto {APP_PORT}")
    sock = dev.connect(APP_PORT)
    if inspect.isawaitable(sock):
        sock = await sock
    sock.setblocking(False)
    r, w = await asyncio.open_connection(sock=sock)
    return Link(r, w, "usb", dev.serial)


async def open_net(ip, port=APP_PORT):
    log(f"conectando por red a {ip}:{port}")
    r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), 5)
    return Link(r, w, "net", f"{ip}:{port}")


def http_base(ws_url):
    """http://host[:puerto] del servidor a partir de su URL de WebSocket."""
    scheme, rest = ws_url.split("://", 1)
    return ("https" if scheme == "wss" else "http") + "://" + rest.split("/", 1)[0]


async def app_target(ws_url):
    """(ip, puerto) de la app que pidió conexión por red al servidor (/connect), o None."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(http_base(ws_url) + "/bridge/target", timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status != 200:
                    return None
                d = await r.json()
    except Exception:
        return None
    if d.get("ip"):
        return d["ip"], int(d.get("port") or APP_PORT)
    return None


async def open_link(target, ws_url, fallback_ip=None):
    """Primera conexión. target: 'usb', 'auto' (USB si está, si no la app que pidió /connect, si no fallback_ip) o una IP.
    Lanza RuntimeError si no hay a quién conectarse (el bucle principal reintenta)."""
    if target in ("usb", "auto"):
        link = await open_usb()
        if link is not None:
            return link
        if target == "usb":
            raise RuntimeError("no hay iPad por USB (¿está instalado 'Dispositivos Apple' y el iPad confía en esta PC?)")
        asked = await app_target(ws_url)
        if asked is not None:
            log(f"sin iPad por USB; la app pidió conexión desde {asked[0]}:{asked[1]}")
            return await open_net(*asked)
        if not fallback_ip:
            raise RuntimeError("no hay iPad por USB ni app que haya pedido conexión (/connect) ni IP de respaldo")
        log(f"sin iPad por USB, usando red {fallback_ip}:{APP_PORT}")
        return await open_net(fallback_ip)
    return await open_net(target)


class Session:
    """Una conexión con el servidor y la conexión vigente con la app; esta última puede migrar de red a USB."""

    def __init__(self, ws, link):
        self.ws, self.link = ws, link
        self.ws_last_rx = time.monotonic()
        self.ws_pongs = 0
        self.config = None         # último vconfig ya enmarcado: la conexión nueva tras migrar lo necesita antes del video

    async def ws_to_ipad(self):
        async for msg in self.ws:
            self.ws_last_rx = time.monotonic()
            link = self.link
            if msg.type == aiohttp.WSMsgType.BINARY:
                if msg.data[0] == 2:          # imagen fija PNG
                    link.write(frame(T_STILL, msg.data[1:]))
                else:
                    link.write(frame(T_VIDEO, msg.data))
            elif msg.type == aiohttp.WSMsgType.TEXT:
                m = json.loads(msg.data)
                t = m.get("type")
                if t == "vconfig" and m.get("description"):
                    # byte 1 = códec (1 avcC/H.264, 2 hvcC/HEVC) + record
                    codec = 2 if m["codec"].startswith(("hvc1", "hev1")) else 1
                    self.config = frame(T_CONFIG, bytes([codec]) + base64.b64decode(m["description"]))
                    link.write(self.config)
                    log(f"config {m['codec']} {m['width']}x{m['height']}")
                elif t == "still-clear":
                    link.write(frame(T_STILLCLEAR, b""))
                elif t == "pong" and m.get("tag") == "bridge":
                    self.ws_pongs += 1        # respuesta a nuestro propio ping: no es para la app
                    continue
                elif t == "welcome":
                    log(f"servidor: bienvenida de {m.get('name')} (id {m.get('id')})")
                    link.write(frame(T_CTRL_DOWN, msg.data.encode()))
                elif t == "auth":
                    # No debería pasar (el servidor confía en esta PC): avisar y dejar que la app lo muestre.
                    log(f"servidor pide emparejamiento: {m}")
                    link.write(frame(T_CTRL_DOWN, msg.data.encode()))
                elif t in CTRL_DOWN_TYPES:
                    link.write(frame(T_CTRL_DOWN, msg.data.encode()))
                else:
                    continue
            else:
                return
            await link.drain()

    async def ipad_to_ws(self):
        while True:
            link = self.link
            try:
                t, body = await link.read()
            except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
                if link is self.link:
                    raise ConnectionError(f"la app cerró la conexión por {link.transport} ({type(e).__name__})")
                continue              # era la conexión vieja, ya migramos a la nueva
            if link is not self.link:
                continue              # resto de la conexión vieja
            if t == T_INPUT:
                m = json.loads(body)
                m["type"] = "input"
                await self.ws.send_str(json.dumps(m))
            elif t == T_NEEDKEY:
                await self.ws.send_str(json.dumps({"type": "need-key"}))
            elif t == T_PING:
                if not link.echoes:
                    log(f"la app devuelve el latido ({link.transport}): corte por silencio activo")
                link.echoes = True    # la app devuelve el latido
            elif t == T_CTRL_UP:
                m = json.loads(body)
                kind = m.get("type")
                if kind not in CTRL_UP_TYPES:
                    continue
                if kind == "stats":
                    m["transport"] = link.transport
                await self.ws.send_str(json.dumps(m))
                if kind == "closing":
                    raise ConnectionError("la app avisó que se cierra")

    async def heartbeat(self):
        # Sin video no circula nada: el latido detecta en segundos si la app se cerró o el cable se soltó, y el ping
        # al servidor mantiene viva la sesión (el servidor corta a los 5 s sin bytes) y detecta si el servidor cayó.
        while True:
            link = self.link
            now = time.monotonic()
            if link.echoes and now - link.last_rx > LIVENESS:
                raise ConnectionError(f"la app no responde hace {now - link.last_rx:.0f} s ({link.transport})")
            if now - self.ws_last_rx > LIVENESS:
                raise ConnectionError(f"el servidor no responde hace {now - self.ws_last_rx:.0f} s")
            link.write(frame(T_PING, b""))
            await link.drain()
            await self.ws.send_str(json.dumps({"type": "ping", "t": int(time.time() * 1000), "tag": "bridge"}))
            await asyncio.sleep(2)

    async def watch_usb(self):
        # Conectados por red: si aparece el iPad por USB, migrar la sesión al cable sin cortar la del servidor.
        if self.link.transport != "net":
            await asyncio.Event().wait()      # por USB no hay nada que vigilar: si el cable se suelta, la lectura falla
        while True:
            await asyncio.sleep(USB_POLL)
            if self.link.transport != "net":
                return
            try:
                new = await open_usb()
            except Exception as e:
                log(f"el cable apareció pero no pude abrir el puerto: {type(e).__name__}: {e}")
                continue
            if new is not None:
                await self.migrate(new)
                await asyncio.Event().wait()  # ya por cable: esta tarea no termina (terminar cortaría la sesión)

    async def migrate(self, new):
        """La app aceptó la conexión nueva (y cierra la vieja por su cuenta): desde ahora todo va por ella."""
        old, self.link = self.link, new
        log(f"sesión migrada de {old.transport} ({old.where}) a {new.transport} ({new.where})")
        old.close()
        if self.config is not None:
            new.write(self.config)    # el servidor no repite el vconfig si no cambió: se lo damos nosotros
        new.write(frame(T_PING, b""))
        await new.drain()
        await self.ws.send_str(json.dumps({"type": "transport", "transport": new.transport}))
        await self.ws.send_str(json.dumps({"type": "need-key"}))   # la app empieza de cero en la conexión nueva


async def run(target, ws_url, fallback_ip=None):
    link = await open_link(target, ws_url, fallback_ip)
    log(f"app del iPad conectada por {link.transport} ({link.where})")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, max_msg_size=32 * 1024 * 1024) as ws:
                s = Session(ws, link)
                await ws.send_str(json.dumps({"type": "hello", "role": "ipad", "transport": link.transport, "name": "app iPad"}))
                log(f"registrado como visor en {ws_url}")
                tasks = [asyncio.create_task(c()) for c in (s.ws_to_ipad, s.ipad_to_ws, s.heartbeat, s.watch_usb)]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
                for d in done:
                    if d.exception():
                        log(f"terminó: {d.exception()!r}")
                link = s.link
                return link.transport
    finally:
        link.close()


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "usb"
    ws_url = sys.argv[2] if len(sys.argv) > 2 else "ws://localhost/ws"
    fallback_ip = sys.argv[3] if len(sys.argv) > 3 else None
    wait = 2
    while True:
        t0 = time.monotonic()
        try:
            last = await run(target, ws_url, fallback_ip)
            if last == "usb":
                log("la sesión por USB terminó (¿cable desenchufado?): vuelvo a buscar el iPad")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # red caída, app cerrada, usbmuxd que rechaza (Number 3 = nadie escucha en el iPad)...
            log(f"{type(e).__name__}: {e}")
        # Backoff: si la sesión duró, reintentar enseguida; si falla seguido, esperar hasta 10 s
        wait = 2 if time.monotonic() - t0 > 30 else min(wait * 1.5, 10)
        log(f"reintento en {wait:.0f} s")
        await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(main())
