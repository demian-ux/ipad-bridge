"""Puente entre el servidor (WebSocket) y la app nativa del iPad (TCP por USB vía usbmux, o por IP).

Se conecta al servidor como un visor más ("ipad"), así que la página de la PC no cambia:
recibe vconfig + frames HEVC y los reenvía a la app con el framing u32 largo + u8 tipo.
Los eventos del Pencil vuelven por el mismo socket y se entregan al servidor como input.
Corre en la misma PC que el servidor, por eso el servidor lo acepta sin código de emparejamiento: por USB el cable
es la autorización; por IP la escribió el dueño de la PC.

Transporte en caliente: mientras la sesión va por red vigila usbmux y, si aparece el cable, abre la conexión USB;
cuando la app la acepta migra la sesión a ella (la conexión con el servidor es la misma) y cierra la de red. El servidor
recibe {"type":"transport","transport":"usb"} y reinicia la captura con el bitrate de USB: el corte es un keyframe.
Si se desenchufa el cable la sesión termina y se espera el cable de nuevo; solo vuelve por red si hay IP de respaldo.

Liveness: latido (tipo 0) cada 2 s hacia la app, que lo devuelve; 5 s sin bytes de un lado cortan la sesión y se
reintenta con espera creciente (2 → 10 s). Lo mismo con el servidor (ping/pong JSON).

Uso:
  python usb_bridge.py                 # USB: primer iPad conectado (requiere "Dispositivos Apple" o iTunes instalado)
  python usb_bridge.py 192.168.1.63    # por red: IP del iPad (cable Ethernet o Wi-Fi), sin usbmux
  python usb_bridge.py usb ws://localhost/ws
  python usb_bridge.py auto ws://localhost/ws 192.168.1.63   # USB si está disponible, si no por red (respaldo)
"""
import asyncio
import base64
import inspect
import json
import socket
import struct
import sys
import time

import aiohttp

APP_PORT = 7777
T_PING, T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY = 0, 1, 2, 3, 4, 16, 17
T_CTRL_UP, T_CTRL_DOWN = 18, 19      # JSON de control: iPad->PC (ping, sleeping, wake, closing), PC->iPad (welcome, pong, transport)
CTRL_UP_TYPES = {"ping", "sleeping", "wake", "closing", "need-key"}
CTRL_DOWN_TYPES = {"welcome", "auth", "pong", "transport"}
LIVENESS = 5.0
USB_POLL = 2.0


def frame(t, payload):
    return struct.pack(">IB", 1 + len(payload), t) + payload


async def usb_device():
    """iPad visible por USB vía el servicio de Apple (app 'Dispositivos Apple' o iTunes), o None."""
    try:
        from pymobiledevice3 import usbmux
        dev = usbmux.select_device(connection_type="USB")
        if inspect.isawaitable(dev):
            dev = await dev
        return dev
    except Exception as e:  # usbmuxd ausente, sin dispositivos, etc.
        print(f"[usb] usbmux: {type(e).__name__}: {e}")
        return None


class Link:
    """Una conexión TCP con la app del iPad, por USB ("usb") o por IP ("net")."""

    def __init__(self, reader, writer, transport):
        self.reader, self.writer, self.transport = reader, writer, transport
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
    dev = await usb_device()
    if dev is None:
        return None
    print(f"[usb] iPad {dev.serial} por USB, abriendo puerto {APP_PORT}")
    sock = dev.connect(APP_PORT)
    if inspect.isawaitable(sock):
        sock = await sock
    sock.setblocking(False)
    r, w = await asyncio.open_connection(sock=sock)
    return Link(r, w, "usb")


async def open_net(ip):
    print(f"[usb] conectando por red a {ip}:{APP_PORT}")
    r, w = await asyncio.wait_for(asyncio.open_connection(ip, APP_PORT), 5)
    return Link(r, w, "net")


async def open_link(target, fallback_ip=None):
    """Primera conexión. target: 'usb', 'auto' (USB si está, si no fallback_ip) o una IP."""
    if target in ("usb", "auto"):
        link = await open_usb()
        if link is not None:
            return link
        if target == "usb" or not fallback_ip:
            raise RuntimeError("no hay iPad por USB (¿está instalado 'Dispositivos Apple' y el iPad confía en esta PC?)")
        print(f"[usb] sin iPad por USB, usando red {fallback_ip}:{APP_PORT}")
        return await open_net(fallback_ip)
    return await open_net(target)


class Session:
    """Una conexión con el servidor y la conexión vigente con la app; esta última puede migrar de red a USB."""

    def __init__(self, ws, link):
        self.ws, self.link = ws, link
        self.ws_last_rx = time.monotonic()

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
                    link.write(frame(T_CONFIG, bytes([codec]) + base64.b64decode(m["description"])))
                    print(f"[usb] config {m['codec']} {m['width']}x{m['height']}")
                elif t == "still-clear":
                    link.write(frame(T_STILLCLEAR, b""))
                elif t in CTRL_DOWN_TYPES:
                    link.write(frame(T_CTRL_DOWN, msg.data.encode()))
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
            if t == T_INPUT:
                m = json.loads(body)
                m["type"] = "input"
                await self.ws.send_str(json.dumps(m))
            elif t == T_NEEDKEY:
                await self.ws.send_str(json.dumps({"type": "need-key"}))
            elif t == T_PING:
                link.echoes = True    # la app devuelve el latido
            elif t == T_CTRL_UP:
                m = json.loads(body)
                if m.get("type") in CTRL_UP_TYPES:
                    await self.ws.send_str(json.dumps(m))
                    if m.get("type") == "closing":
                        raise ConnectionError("la app avisó que se cierra")

    async def heartbeat(self):
        # Sin video no circula nada: el latido detecta en segundos si la app se cerró o el cable se soltó, y el ping
        # al servidor mantiene viva la sesión (el servidor corta a los 5 s sin bytes).
        while True:
            link = self.link
            now = time.monotonic()
            if link.echoes and now - link.last_rx > LIVENESS:
                raise ConnectionError(f"la app no responde hace {now - link.last_rx:.0f} s ({link.transport})")
            if now - self.ws_last_rx > LIVENESS:
                raise ConnectionError(f"el servidor no responde hace {now - self.ws_last_rx:.0f} s")
            link.write(frame(T_PING, b""))
            await link.drain()
            await self.ws.send_str(json.dumps({"type": "ping", "t": int(time.time() * 1000)}))
            await asyncio.sleep(2)

    async def watch_usb(self):
        # Conectados por red: si aparece el iPad por USB, migrar la sesión al cable sin cortar la del servidor.
        while True:
            if self.link.transport != "net":
                await asyncio.Event().wait()
            await asyncio.sleep(USB_POLL)
            if self.link.transport != "net":
                continue
            try:
                new = await open_usb()
            except Exception as e:
                print(f"[usb] el cable apareció pero no pude abrir el puerto: {type(e).__name__}: {e}")
                continue
            if new is not None:
                await self.migrate(new)

    async def migrate(self, new):
        """La app aceptó la conexión nueva (y cerró la vieja): desde ahora todo va por ella."""
        old, self.link = self.link, new
        print(f"[usb] sesión migrada de {old.transport} a {new.transport}")
        old.close()
        await self.ws.send_str(json.dumps({"type": "transport", "transport": new.transport}))
        await self.ws.send_str(json.dumps({"type": "need-key"}))


async def run(target, ws_url, fallback_ip=None):
    link = await open_link(target, fallback_ip)
    print(f"[usb] app del iPad conectada por {link.transport}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, max_msg_size=32 * 1024 * 1024) as ws:
                s = Session(ws, link)
                await ws.send_str(json.dumps({"type": "hello", "role": "ipad", "transport": link.transport, "name": "app iPad"}))
                print(f"[usb] registrado como visor en {ws_url}")
                tasks = [asyncio.create_task(c()) for c in (s.ws_to_ipad, s.ipad_to_ws, s.heartbeat, s.watch_usb)]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
                for d in done:
                    if d.exception():
                        print("[usb] terminó:", repr(d.exception()))
                link = s.link
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
            await run(target, ws_url, fallback_ip)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # red caída, app cerrada, usbmuxd que rechaza (Number 3 = nadie escucha en el iPad)...
            print(f"[usb] {type(e).__name__}: {e}")
        # Backoff: si la sesión duró, reintentar enseguida; si falla seguido, esperar hasta 10 s
        wait = 2 if time.monotonic() - t0 > 30 else min(wait * 1.5, 10)
        print(f"[usb] reintento en {wait:.0f} s")
        await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(main())
