"""Simula la app del iPad en la PC para probar usb_bridge.py sin iPad: escucha en 7777 con el mismo framing,
cuenta frames/config recibidos, devuelve el latido (tipo 0), manda ping JSON cada 2 s, un need-key y un input de prueba.
Termina solo tras unos segundos.
Uso: python tools/fake_app.py [segundos=25] [puerto=7777] [--sleep=N] [--mute]
  --sleep=N  a los N s manda {"type":"sleeping"} y 5 s después {"type":"wake"} (la captura se detiene y vuelve)
  --mute     no devuelve el latido ni manda ping (como la app vieja: el puente no debe cortarla por silencio)
Con IPADBRIDGE_FAKE_USB=<puerto> en el puente, una segunda copia en ese puerto hace de "cable" para probar la migración."""
import asyncio
import json
import struct
import sys
import time

PORT = 7777
T_PING, T_VIDEO, T_CONFIG, T_STILL, T_STILLCLEAR, T_INPUT, T_NEEDKEY, T_CTRL_UP, T_CTRL_DOWN = 0, 1, 2, 3, 4, 16, 17, 18, 19
stats = {"config": 0, "video": 0, "key": 0, "bytes": 0, "still": 0, "still_bytes": 0, "clear": 0, "ping": 0, "pong": 0,
         "ctrl": [], "conns": 0, "first_key_s": None, "key_after_wake_s": None}
opts = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1") for a in sys.argv[1:] if a.startswith("--"))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
T0 = time.monotonic()


def frame(t, payload=b""):
    return struct.pack(">IB", 1 + len(payload), t) + payload


def say(msg):
    print(f"[fake] {time.monotonic() - T0:5.1f}s {msg}", flush=True)


async def control(writer):
    """Ping JSON cada 2 s (como la app nueva) y, con --sleep, el par sleeping/wake."""
    sleep_at = float(opts["sleep"]) if "sleep" in opts else None
    woke = None
    while True:
        await asyncio.sleep(2)
        if "mute" not in opts:
            writer.write(frame(T_CTRL_UP, json.dumps({"type": "ping", "t": time.monotonic() * 1000, "q": 0, "d": 0}).encode()))
        now = time.monotonic() - T0
        if sleep_at is not None and now >= sleep_at:
            writer.write(frame(T_CTRL_UP, json.dumps({"type": "sleeping"}).encode()))
            say("mandé sleeping (la captura debería detenerse)")
            sleep_at, woke = None, now + 5
        if woke is not None and now >= woke:
            writer.write(frame(T_CTRL_UP, json.dumps({"type": "wake"}).encode()))
            writer.write(frame(T_NEEDKEY))
            stats["wake_at"] = time.monotonic()
            say("mandé wake + need-key")
            woke = None
        await writer.drain()


async def handle(reader, writer):
    stats["conns"] += 1
    say(f"PC conectada (conexión {stats['conns']})")
    writer.write(frame(T_NEEDKEY))
    await writer.drain()
    sent_input = False
    ctl = asyncio.create_task(control(writer))
    try:
        while True:
            head = await reader.readexactly(5)
            length, t = struct.unpack(">IB", head)
            body = await reader.readexactly(length - 1)
            if t == T_PING:                      # latido del puente: devolverlo (liveness en los dos sentidos)
                stats["ping"] += 1
                if "mute" not in opts:
                    writer.write(frame(T_PING))
                    await writer.drain()
            elif t == T_CTRL_DOWN:                 # welcome / pong / transport / app en JSON
                m = json.loads(body)
                if m.get("type") == "pong":
                    stats["pong"] += 1
                else:
                    stats["ctrl"].append(m.get("type"))
                    say(f"control: {m}")
            elif t == T_CONFIG:
                stats["config"] += 1
                say(f"config codec={body[0]} record {len(body) - 1} bytes")
                open("fake_config.bin", "wb").write(body)
            elif t == T_STILL:
                stats["still"] += 1; stats["still_bytes"] += len(body)
                if stats["still"] == 1:
                    open("fake_still.png", "wb").write(body)
                say(f"imagen fija PNG {len(body) / 1e6:.1f} MB")
            elif t == T_STILLCLEAR:
                stats["clear"] += 1
            elif t == T_VIDEO:
                stats["video"] += 1
                stats["bytes"] += len(body) - 9
                if body[0] == 1:
                    stats["key"] += 1
                    if stats["key"] == 1:
                        stats["first_key_s"] = round(time.monotonic() - T0, 2)
                        open("fake_key.bin", "wb").write(body[9:])
                    if stats.get("wake_at") and stats["key_after_wake_s"] is None:
                        stats["key_after_wake_s"] = round(time.monotonic() - stats["wake_at"], 2)
                    say(f"keyframe ({len(body) / 1e3:.0f} KB)")
                if stats["video"] == 30 and not sent_input:
                    sent_input = True
                    payload = json.dumps({"ev": "move", "x": 0.3, "y": 0.3}).encode()
                    writer.write(frame(T_INPUT, payload))
                    writer.write(frame(T_NEEDKEY))
                    await writer.drain()
                    say("mandé input + need-key")
    except (asyncio.IncompleteReadError, ConnectionError):
        say("PC desconectada")
    finally:
        ctl.cancel()


async def main():
    port = int(args[1]) if len(args) > 1 else PORT
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    say(f"escuchando en {port}" + (" (muda: sin latido ni ping)" if "mute" in opts else ""))
    await asyncio.sleep(float(args[0]) if len(args) > 0 else 25)
    server.close()
    stats.pop("wake_at", None)
    print("[fake] resultado:", json.dumps(stats), flush=True)


asyncio.run(main())
