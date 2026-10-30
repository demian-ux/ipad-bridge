"""Puente entre el servidor (WebSocket) y la app nativa del iPad (TCP por USB vía usbmux, o por IP).

Se conecta al servidor como un visor más ("ipad"), así que la página de la PC no cambia:
recibe vconfig + frames H.264 y los reenvía a la app con el framing u32 largo + u8 tipo.
Los eventos del Pencil vuelven por el mismo socket y se entregan al servidor como input.

Uso:
  python usb_bridge.py                 # USB: primer iPad conectado (requiere "Dispositivos Apple" o iTunes instalado)
  python usb_bridge.py 192.168.1.63    # por red: IP del iPad (cable Ethernet o Wi-Fi), sin usbmux
  python usb_bridge.py usb ws://localhost/ws
  python usb_bridge.py auto ws://localhost/ws 192.168.1.63   # USB si está disponible, si no por red
"""
import asyncio
import base64
import inspect
import json
import socket
import struct
import sys

import aiohttp

APP_PORT = 7777
T_PING, T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY = 0, 1, 2, 3, 4, 16, 17
T_CTRL_UP, T_CTRL_DOWN = 18, 19      # JSON de control tal cual va por el WebSocket: iPad->PC (ping, stats, quality), PC->iPad (pong)
CTRL_UP_TYPES = {"ping", "stats", "quality", "need-key"}
CTRL_DOWN_TYPES = {"pong"}


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


async def open_ipad(target, fallback_ip=None):
    """Devuelve (reader, writer) de asyncio hacia la app del iPad.
    target: 'usb', 'auto' (USB si está, si no fallback_ip) o una IP."""
    if target == "auto":
        dev = await usb_device()
        if dev is None and fallback_ip:
            print(f"[usb] sin iPad por USB, usando red {fallback_ip}:{APP_PORT}")
            r, w = await asyncio.open_connection(fallback_ip, APP_PORT)
            w._via_net = True
            return r, w
        if dev is None:
            raise RuntimeError("no hay iPad por USB y no se indicó IP de respaldo")
        target = "usb"
    if target != "usb":
        print(f"[usb] conectando por red a {target}:{APP_PORT}")
        return await asyncio.open_connection(target, APP_PORT)
    from pymobiledevice3 import usbmux
    dev = usbmux.select_device(connection_type="USB")
    if inspect.isawaitable(dev):
        dev = await dev
    if dev is None:
        raise RuntimeError("no hay iPad por USB (¿está instalado 'Dispositivos Apple' y el iPad confía en esta PC?)")
    print(f"[usb] iPad {dev.serial} por USB, abriendo puerto {APP_PORT}")
    sock = dev.connect(APP_PORT)
    if inspect.isawaitable(sock):
        sock = await sock
    sock.setblocking(False)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return await asyncio.open_connection(sock=sock)


def tune(writer):
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass


async def run(target, ws_url, fallback_ip=None):
    reader, writer = await open_ipad(target, fallback_ip)
    tune(writer)
    print("[usb] app del iPad conectada")
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url, max_msg_size=32 * 1024 * 1024) as ws:
            transport = "net" if getattr(writer, "_via_net", False) or (target not in ("usb", "auto")) else "usb"
            await ws.send_str(json.dumps({"type": "hello", "role": "ipad", "transport": transport}))
            print(f"[usb] registrado como visor en {ws_url}")

            async def ws_to_ipad():
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        if msg.data[0] == 2:          # imagen fija PNG
                            writer.write(frame(T_STILL, msg.data[1:]))
                        else:
                            writer.write(frame(T_VIDEO, msg.data))
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        m = json.loads(msg.data)
                        if m.get("type") == "vconfig" and m.get("description"):
                            # byte 1 = códec (1 avcC/H.264, 2 hvcC/HEVC) + record
                            codec = 2 if m["codec"].startswith(("hvc1", "hev1")) else 1
                            writer.write(frame(T_CONFIG, bytes([codec]) + base64.b64decode(m["description"])))
                            print(f"[usb] config {m['codec']} {m['width']}x{m['height']}")
                        elif m.get("type") == "still-clear":
                            writer.write(frame(T_STILLCLEAR, b""))
                        elif m.get("type") in CTRL_DOWN_TYPES:
                            writer.write(frame(T_CTRL_DOWN, msg.data.encode()))
                    else:
                        break
                    await writer.drain()

            async def ipad_to_ws():
                while True:
                    head = await reader.readexactly(5)
                    length, t = struct.unpack(">IB", head)
                    body = await reader.readexactly(length - 1)
                    if t == T_INPUT:
                        m = json.loads(body)
                        m["type"] = "input"
                        await ws.send_str(json.dumps(m))
                    elif t == T_NEEDKEY:
                        await ws.send_str(json.dumps({"type": "need-key"}))
                    elif t == T_CTRL_UP:                  # ping, stats, quality...: al servidor tal cual
                        m = json.loads(body)
                        if m.get("type") not in CTRL_UP_TYPES:
                            continue
                        if m.get("type") == "stats":
                            m["transport"] = transport
                        await ws.send_str(json.dumps(m))

            async def heartbeat():
                # Sin video no circula nada: el latido detecta en segundos si la app se cerró o se relanzó.
                while True:
                    writer.write(frame(T_PING, b""))
                    await writer.drain()
                    await asyncio.sleep(2)

            async def watch_usb():
                # Conectados por red: si aparece el iPad por USB, cortar para reconectar por el cable.
                if not getattr(writer, "_via_net", False):
                    await asyncio.Event().wait()
                while True:
                    await asyncio.sleep(3)
                    if await usb_device() is not None:
                        print("[usb] iPad detectado por USB: cambiando de red a cable")
                        return

            done, pending = await asyncio.wait(
                [asyncio.create_task(ws_to_ipad()), asyncio.create_task(ipad_to_ws()), asyncio.create_task(heartbeat()),
                 asyncio.create_task(watch_usb())],
                return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            for d in done:
                if d.exception():
                    print("[usb] terminó:", repr(d.exception()))
    writer.close()


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "usb"
    ws_url = sys.argv[2] if len(sys.argv) > 2 else "ws://localhost/ws"
    fallback_ip = sys.argv[3] if len(sys.argv) > 3 else None
    while True:
        try:
            await run(target, ws_url, fallback_ip)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # red caída, app cerrada, usbmuxd que rechaza (Number 3 = nadie escucha en el iPad)...
            print(f"[usb] {type(e).__name__}: {e}")
        print("[usb] reintento en 2 s")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
