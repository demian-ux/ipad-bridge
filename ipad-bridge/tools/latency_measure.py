"""Mide la latencia captura -> salida del encoder: con tools/latency_clock.py en pantalla, graba el flujo del servidor
con el ts de cada frame, lo decodifica con ffmpeg y lee en cada frame los 32 bits del reloj dibujado.
latencia = ts del frame (reloj del servidor, ms) - (reloj dibujado + anclaje), donde el anclaje reloj QPC -> reloj del
servidor sale del pong (s - perf_counter al recibirlo, error < 1 ms por localhost).
Uso: python tools/latency_measure.py [ws://localhost:8080/ws] [segundos=8] [x=100] [y=100]
(lanzá antes `python tools/latency_clock.py 30 100 100`; x,y los mismos). Resultado: p50/p95 en ms."""
import asyncio
import json
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stream_probe import hvcc_nals  # noqa: E402

SQ, BITS = 40, 32


async def grab(url, secs):
    """Devuelve (anclaje, lista de (ts, annexb_bytes)) de `secs` segundos de flujo."""
    import base64
    frames, anchor, params = [], None, b""
    t0 = time.perf_counter()
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url, max_msg_size=64 * 1024 * 1024) as ws:
            await ws.send_str(json.dumps({"type": "hello", "role": "ipad", "transport": "usb"}))
            await ws.send_str(json.dumps({"type": "ping", "t": 0}))
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    m = json.loads(msg.data)
                    if m["type"] == "vconfig":
                        params = b"".join(b"\x00\x00\x00\x01" + n for n in hvcc_nals(base64.b64decode(m["description"])))
                        wh = (m["width"], m["height"])
                    elif m["type"] == "pong":
                        anchor = m["mt"] - time.perf_counter() * 1000   # reloj servidor = QPC ms + anchor
                elif msg.type == aiohttp.WSMsgType.BINARY and msg.data[0] != 2:
                    d = msg.data
                    ts = struct.unpack(">d", d[1:9])[0]
                    out, i = [], 9
                    while i < len(d):
                        ln = struct.unpack(">I", d[i:i + 4])[0]
                        out.append(b"\x00\x00\x00\x01" + d[i + 4:i + 4 + ln])
                        i += 4 + ln
                    if d[0] == 1 or frames:
                        frames.append((ts, b"".join(out)))
                if time.perf_counter() - t0 > secs:
                    break
    return anchor, params, frames, wh


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = args[0] if args else "ws://localhost:8080/ws"
    secs = float(args[1]) if len(args) > 1 else 8
    X = int(args[2]) if len(args) > 2 else 100
    Y = int(args[3]) if len(args) > 3 else 100
    anchor, params, frames, (w, h) = asyncio.run(grab(url, secs))
    print(f"{len(frames)} frames, anclaje {anchor:.1f}")
    tmp = Path(tempfile.mkdtemp())
    (tmp / "in.hevc").write_bytes(params + b"".join(f for _, f in frames))
    # Decodificar solo la fila de cuadrados (crop) a gris de 8 bits.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(tmp / "in.hevc"),
           "-vf", f"crop={SQ * (BITS + 2)}:{SQ}:{X}:{Y + SQ},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", str(tmp / "rows.gray")]
    subprocess.run(cmd, check=True)
    rows = np.fromfile(tmp / "rows.gray", dtype=np.uint8).reshape(-1, SQ, SQ * (BITS + 2))
    lat, bad = [], 0
    for (ts, _), row in zip(frames, rows):
        cells = row[SQ // 4: 3 * SQ // 4, :].reshape(SQ // 2, BITS + 2, SQ)[:, :, SQ // 4: 3 * SQ // 4].mean(axis=(0, 2))
        bits = cells > 128
        if bits[0] or not bits[-1]:
            bad += 1
            continue
        v = 0
        for b in bits[1:-1]:
            v = (v << 1) | int(b)
        drawn = v + anchor            # reloj del servidor cuando se dibujó el frame (módulo 2^32 ms: no importa en 8 s)
        d = (ts - drawn) % (1 << 32)
        if d < 1000:
            lat.append(d)
    lat.sort()
    if not lat:
        print("no pude leer el reloj (¿está latency_clock.py en pantalla en esas coordenadas?)")
        return
    print(f"captura->salida del encoder: p50 {lat[len(lat) // 2]:.1f} ms · p95 {lat[int(len(lat) * .95)]:.1f} ms · "
          f"mín {lat[0]:.1f} · máx {lat[-1]:.1f} · {len(lat)} frames leídos, {bad} sin sincronismo")


if __name__ == "__main__":
    main()
