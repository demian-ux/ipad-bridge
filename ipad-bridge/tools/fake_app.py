"""Simula la app del iPad en la PC para probar usb_bridge.py sin iPad: escucha en 7777 con el mismo framing,
cuenta frames/config recibidos, devuelve el latido y manda un need-key y un input de prueba. Termina solo tras unos
segundos.   Uso: python tools/fake_app.py [segundos] [puerto]"""
import asyncio
import json
import struct
import sys

PORT = 7777
T_PING, T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY, T_CTRL_UP, T_CTRL_DOWN = 0, 1, 2, 3, 4, 16, 17, 18, 19
stats = {"config": 0, "video": 0, "key": 0, "bytes": 0, "still": 0, "still_bytes": 0, "clear": 0, "ping": 0, "ctrl": []}


async def handle(reader, writer):
    print("[fake] PC conectada")
    writer.write(struct.pack(">IB", 1, T_NEEDKEY))
    await writer.drain()
    sent_input = False
    try:
        while True:
            head = await reader.readexactly(5)
            length, t = struct.unpack(">IB", head)
            body = await reader.readexactly(length - 1)
            if t == T_PING:                      # latido del puente: devolverlo (liveness en los dos sentidos)
                stats["ping"] += 1
                writer.write(struct.pack(">IB", 1, T_PING))
                await writer.drain()
            elif t == T_CTRL_DOWN:                 # welcome / pong / transport en JSON
                m = json.loads(body)
                stats["ctrl"].append(m.get("type"))
                if m.get("type") == "welcome":
                    print("[fake] welcome:", {k: v for k, v in m.items() if k != "token"})
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
            elif t == T_VIDEO:
                stats["video"] += 1
                stats["bytes"] += len(body) - 9
                if body[0] == 1:
                    stats["key"] += 1
                    if stats["key"] == 1:
                        open("fake_key.bin", "wb").write(body[9:])
                if stats["video"] == 30 and not sent_input:
                    sent_input = True
                    payload = json.dumps({"ev": "move", "x": 0.3, "y": 0.3}).encode()
                    writer.write(struct.pack(">IB", 1 + len(payload), T_INPUT) + payload)
                    writer.write(struct.pack(">IB", 1, T_NEEDKEY))
                    await writer.drain()
                    print("[fake] mandé input + need-key")
    except asyncio.IncompleteReadError:
        print("[fake] PC desconectada")


async def main():
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    print(f"[fake] escuchando en {port}", flush=True)
    await asyncio.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 25)
    server.close()
    print("[fake] resultado:", json.dumps(stats), flush=True)


asyncio.run(main())
