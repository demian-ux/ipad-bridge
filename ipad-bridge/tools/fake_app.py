"""Simula la app del iPad en la PC para probar usb_bridge.py sin iPad: escucha en 7777 con el mismo framing,
cuenta frames/config recibidos y manda un need-key y un input de prueba. Termina solo tras unos segundos."""
import asyncio
import json
import struct
import sys

PORT = 7777
T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY = 1, 2, 3, 4, 16, 17
stats = {"config": 0, "video": 0, "key": 0, "bytes": 0, "still": 0, "still_bytes": 0, "clear": 0}


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
            if t == T_CONFIG:
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
    server = await asyncio.start_server(handle, "127.0.0.1", PORT)
    print(f"[fake] escuchando en {PORT}", flush=True)
    await asyncio.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 25)
    server.close()
    print("[fake] resultado:", json.dumps(stats), flush=True)


asyncio.run(main())
