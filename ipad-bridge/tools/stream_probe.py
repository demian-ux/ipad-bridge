"""Visor de medición sin iPad: se conecta al servidor como un visor más y mide lo que llega.
Uso: python tools/stream_probe.py [ws://localhost:8080/ws] [segundos=20] [--transport=usb|net] [--dump=salida.hevc]
                                  [--need-key=8] [--quality=auto|draw|motion] [--sick=4]
Imprime por segundo frames, keyframes, Mbps y tamaño medio de key/delta; al final un resumen JSON con el tiempo hasta
la primera imagen (hello -> vconfig -> primer keyframe), el RTT y offset del reloj (ping/pong) y, con --need-key=N,
cuánto tardó en llegar un keyframe tras pedirlo en el segundo N. --dump guarda el flujo en Annex B (VPS/SPS/PPS al
frente) para decodificarlo con ffmpeg y medir ΔE con tools/color_check.py. --sick=N simula desde el segundo N un visor
que sufre (cola 5 y descartes en cada ping) para ver cómo baja la calidad adaptativa, y a los N+20 s vuelve a estar bien."""
import asyncio
import base64
import json
import statistics
import struct
import sys
import time

import aiohttp

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))


def hvcc_nals(rec):
    """Parameter sets (VPS/SPS/PPS) de un hvcC."""
    out, i, n = [], 23, rec[22]
    for _ in range(n):
        i += 1
        cnt = struct.unpack(">H", rec[i:i + 2])[0]
        i += 2
        for _ in range(cnt):
            ln = struct.unpack(">H", rec[i:i + 2])[0]
            i += 2
            out.append(rec[i:i + ln])
            i += ln
    return out


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1") for a in sys.argv[1:] if a.startswith("--"))
    url = args[0] if args else "ws://localhost:8080/ws"
    secs = float(args[1]) if len(args) > 1 else 20
    need_key_at = float(opts["need-key"]) if "need-key" in opts else None
    sick_at = float(opts["sick"]) if "sick" in opts else None
    dump = open(opts["dump"], "wb") if "dump" in opts else None
    t0 = time.perf_counter()
    res = {"vconfig_s": None, "first_key_s": None, "need_key_s": None, "rtt_ms": [], "pong": [], "seconds": []}
    sec = {"n": 0, "key": 0, "bytes": 0, "kbytes": 0, "dbytes": 0, "t": t0}
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url, max_msg_size=64 * 1024 * 1024, ssl=False) as ws:
            await ws.send_str(json.dumps({"type": "hello", "role": "ipad", "transport": opts.get("transport", "net")}))
            if "quality" in opts:
                await ws.send_str(json.dumps({"type": "quality", "mode": opts["quality"]}))
            need_sent = None
            next_ping, next_report = t0 + 0.5, t0 + 1

            async def rx():
                nonlocal need_sent
                async for msg in ws:
                    now = time.perf_counter()
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        d = msg.data
                        if d[0] == 2:
                            continue
                        key = d[0] == 1
                        n = len(d) - 9
                        sec["n"] += 1
                        sec["bytes"] += n
                        if key:
                            sec["key"] += 1
                            sec["kbytes"] += n
                            if res["first_key_s"] is None:
                                res["first_key_s"] = round(now - t0, 3)
                            if need_sent is not None and res["need_key_s"] is None:
                                res["need_key_s"] = round(now - need_sent, 3)
                        else:
                            sec["dbytes"] += n
                        if dump:
                            i = 9
                            while i < len(d):
                                ln = struct.unpack(">I", d[i:i + 4])[0]
                                dump.write(b"\x00\x00\x00\x01" + d[i + 4:i + 4 + ln])
                                i += 4 + ln
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        m = json.loads(msg.data)
                        if m["type"] == "vconfig":
                            if res["vconfig_s"] is None:
                                res["vconfig_s"] = round(now - t0, 3)
                            res["vconfig"] = {k: m[k] for k in ("codec", "width", "height")}
                            if dump:
                                for nal in hvcc_nals(base64.b64decode(m["description"])):
                                    dump.write(b"\x00\x00\x00\x01" + nal)
                        elif m["type"] == "pong":
                            rtt = (now - t0) * 1000 - m["t"]
                            res["rtt_ms"].append(round(rtt, 2))
                            res["pong"].append({k: v for k, v in m.items() if k not in ("type", "t", "mt")})
                            if sick_at is not None:
                                print(f"[probe] pong {now - t0:5.1f} s: nivel {m.get('level')} escala {m.get('scale')} {m.get('br')} Mbps {m.get('fps')} fps", flush=True)
                    else:
                        break

            task = asyncio.create_task(rx())
            while time.perf_counter() - t0 < secs:
                await asyncio.sleep(0.05)
                now = time.perf_counter()
                if now >= next_ping:
                    next_ping = now + 2
                    sick = sick_at is not None and sick_at <= now - t0 < sick_at + 20
                    await ws.send_str(json.dumps({"type": "ping", "t": (now - t0) * 1000, "q": 5 if sick else 0, "d": 3 if sick else 0}))
                if need_key_at is not None and now - t0 >= need_key_at and need_sent is None:
                    need_sent = now
                    await ws.send_str(json.dumps({"type": "need-key"}))
                    print(f"[probe] need-key enviado en {now - t0:.1f} s", flush=True)
                if now >= next_report:
                    next_report = now + 1
                    dt = now - sec["t"]
                    row = {"s": round(now - t0), "fps": round(sec["n"] / dt), "key": sec["key"], "mbps": round(sec["bytes"] * 8 / dt / 1e6, 2),
                           "kb_key": round(sec["kbytes"] / 1e3 / max(1, sec["key"])), "kb_delta": round(sec["dbytes"] / 1e3 / max(1, sec["n"] - sec["key"]), 1)}
                    res["seconds"].append(row)
                    print("[probe]", json.dumps(row), flush=True)
                    sec.update(n=0, key=0, bytes=0, kbytes=0, dbytes=0, t=now)
            task.cancel()
    if dump:
        dump.close()
    rows = res["seconds"][2:] or res["seconds"]
    res["mbps_median"] = round(statistics.median(r["mbps"] for r in rows), 2) if rows else None
    res["mbps_mean"] = round(statistics.mean(r["mbps"] for r in rows), 2) if rows else None
    res["fps_median"] = statistics.median(r["fps"] for r in rows) if rows else None
    res["keys_total"] = sum(r["key"] for r in rows)
    print("[probe] resumen:", json.dumps({k: v for k, v in res.items() if k != "seconds"}), flush=True)


asyncio.run(main())
