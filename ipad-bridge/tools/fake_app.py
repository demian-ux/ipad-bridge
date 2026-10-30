"""Simula la app del iPad en la PC para probar usb_bridge.py sin iPad: escucha en 7777 con el mismo framing,
cuenta frames/config recibidos, los JSON de control que bajan (pong, app, shortcuts), manda un ping, un need-key
y un input de prueba (pencfg + move). Termina solo tras unos segundos y escribe el resultado como JSON."""
import asyncio
import json
import struct
import sys

PORT = 7777
T_PING, T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY, T_CTRL_UP, T_CTRL_DOWN = 0, 1, 2, 3, 4, 16, 17, 18, 19
stats = {"config": 0, "video": 0, "key": 0, "bytes": 0, "still": 0, "still_bytes": 0, "clear": 0, "ping": 0,
         "ctrl": {}, "app": None, "shortcuts_profiles": None, "unknown": []}


def frame(t, payload=b""):
    return struct.pack(">IB", 1 + len(payload), t) + payload


def ctrl(d):
    return frame(T_CTRL_UP, json.dumps(d).encode())


def inp(d):
    return frame(T_INPUT, json.dumps(d).encode())


async def handle(reader, writer):
    print("[fake] PC conectada")
    # Lo que hace la app real al conectar: pedir keyframe, mandar su curva de presión y un ping para el reloj.
    writer.write(frame(T_NEEDKEY))
    writer.write(inp({"ev": "pencfg", "pen": 1, "gamma": 0.8, "min": 0.02, "smooth": 0}))
    writer.write(ctrl({"type": "ping", "t": 1000.0, "q": 0, "d": 0}))
    await writer.drain()
    sent_input = False
    try:
        while True:
            head = await reader.readexactly(5)
            length, t = struct.unpack(">IB", head)
            body = await reader.readexactly(length - 1)
            if t == T_PING:
                stats["ping"] += 1
            elif t == T_CONFIG:
                stats["config"] += 1
                print(f"[fake] config codec={body[0]} record {len(body) - 1} bytes")
                open("fake_config.bin", "wb").write(body)
            elif t == T_STILL:
                stats["still"] += 1; stats["still_bytes"] += len(body)
                if stats["still"] == 1:
                    open("fake_still.png", "wb").write(body)
                print(f"[fake] imagen fija PNG {len(body) / 1e6:.1f} MB")
            elif t == T_STILLCLEAR:
                stats["clear"] += 1
            elif t == T_CTRL_DOWN:
                m = json.loads(body)
                kind = m.get("type")
                stats["ctrl"][kind] = stats["ctrl"].get(kind, 0) + 1
                if kind == "app":
                    stats["app"] = m.get("exe")
                    print(f"[fake] app activa: {m.get('exe')} ({str(m.get('title', ''))[:40]})")
                elif kind == "shortcuts":
                    profs = m.get("profiles") or []
                    stats["shortcuts_profiles"] = [p.get("id") for p in profs]
                    print(f"[fake] shortcuts: {len(profs)} perfiles {stats['shortcuts_profiles']}, gestos {sorted((m.get('gestures') or {}).keys())}")
                elif kind == "pong":
                    print(f"[fake] pong t={m.get('t')} mt={m.get('mt')}")
            elif t == T_VIDEO:
                stats["video"] += 1
                stats["bytes"] += len(body) - 9
                if body[0] == 1:
                    stats["key"] += 1
                    if stats["key"] == 1:
                        open("fake_key.bin", "wb").write(body[9:])
                if stats["video"] == 30 and not sent_input:
                    sent_input = True
                    writer.write(inp({"ev": "move", "x": 0.3, "y": 0.3}))
                    writer.write(frame(T_NEEDKEY))
                    await writer.drain()
                    print("[fake] mandé input + need-key")
            else:
                stats["unknown"].append(t)
    except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
        print("[fake] PC desconectada")


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", PORT)
    print(f"[fake] escuchando en {PORT}", flush=True)
    await asyncio.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 25)
    server.close()
    print("[fake] resultado:", json.dumps(stats), flush=True)


asyncio.run(main())
