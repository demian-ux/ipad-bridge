"""iPad Bridge: captura el monitor virtual directo de la GPU (ffmpeg ddagrab + NVENC HEVC 10 bits), lo manda a los
visores por WebSocket y aplica el input del iPad. Cuando la pantalla se queda quieta manda además el frame exacto
como PNG (sin pérdida), que el visor muestra encima del video hasta que algo se mueve.

Mensajes a los visores:
  JSON   {"type":"vconfig", codec, width, height, description(base64 hvcC)}
  JSON   {"type":"still-clear"}                      -> volver a mostrar el video
  JSON   {"type":"pong", t, mt, inp50, inp95, ...}   -> respuesta al ping del visor (mt = reloj del servidor en ms)
  binario u8 0|1 (delta|key) + f64 ts + muestra HEVC (NALs con largo de 4 bytes); ts = reloj del servidor en ms
  binario u8 2 + PNG                                 -> imagen fija sin pérdida
Del visor: {"type":"ping","t":reloj del visor}, {"type":"stats",...} cada 5 s, {"type":"quality","mode":"auto|draw|motion"},
{"type":"need-key"} (pide un IDR: reinicia el encoder), {"type":"input", ..., "t": reloj del servidor estimado}.
  JSON   {"type":"app", exe, title}                  -> ventana activa de Windows (barra de atajos por aplicación)
"""
import asyncio
import base64
import io
import json
import logging
import os
import re
import socket
import ssl
import struct
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp import web, WSMsgType

import hevc
from winput import Mouse, Pen, foreground_app, hold_key, release_keys, tap_keys, target_display, tilt_from_angles, type_text

STATIC = Path(__file__).parent / "static"
CERTS = Path(__file__).parent / "certs"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80
TLS_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 443
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
# Bitrate según el transporte del visor: por USB 100 Mbps, por red (Wi-Fi) 50. Los fps siguen al refresco del monitor virtual.
BITRATE_USB, BITRATE_NET = int(os.environ.get("BITRATE_USB", "100")), int(os.environ.get("BITRATE_NET", "50"))
STILL_AFTER = 0.4   # segundos sin cambios en pantalla para mandar el PNG
# Tope de fps de captura: NVENC (RTX 4060) no sostiene 2732x2048 HEVC 10b a 120 fps con movimiento real
# (medido: 0.8-0.95x); a 60 fps sobra margen. MAX_FPS=120 para probar igual.
MAX_FPS = int(os.environ.get("MAX_FPS", "60"))
# Doble toque del Pencil: alterna entre dos atajos en la ventana activa (Photoshop: E = borrador, B = pincel).
# Windows no permite emular el lado goma de un lápiz sintético, por eso va por teclado. Formato "tecla_goma,tecla_vuelta".
PEN_TAP_KEYS = os.environ.get("PEN_TAP_KEYS", "e,b").split(",")
# iPad sin hover: el Pencil "aparece" ya tocando. Un lápiz real entra en alcance antes del contacto, y Photoshop con
# Windows Ink perdía el primer trazo cuando ENTER y DOWN llegaban en el mismo instante. PEN_ARM_MS: ms entre entrar
# en alcance y tocar (los eventos de ese lapso se encolan). PEN_LEAVE_S: segundos quieto tras soltar antes de salir de
# alcance (mientras está en alcance, los trazos siguientes no vuelven a pasar por ENTER).
PEN_ARM_MS = int(os.environ.get("PEN_ARM_MS", "30"))
PEN_LEAVE_S = float(os.environ.get("PEN_LEAVE_S", "1.5"))
# Keyframes. "refresh" (predeterminado): GOP de GOP_S segundos con intra-refresh de NVENC (columnas intra repartidas
# entre los frames: sin pulso de bitrate ni de calidad cada segundo; medido a 3840x2160: reposo 5,1 -> 0,2 Mbps). Un
# visor nuevo pide need-key y el encoder se reinicia para emitir un IDR (~0,3 s). "idr": comportamiento anterior, un
# IDR por segundo (GOP = fps), need-key espera al próximo (hasta 1 s).
KEYFRAMES = os.environ.get("KEYFRAMES", "refresh")
GOP_S = float(os.environ.get("GOP_S", "10" if KEYFRAMES == "refresh" else "1"))
# Calidad adaptativa: "1" (predeterminado) baja bitrate/escala/fps cuando un visor por red sufre (cola, descartes, RTT)
# y vuelve a subir al estabilizarse; "0" la desactiva (queda el preset manual del iPad y el bitrate por transporte).
ADAPTIVE = os.environ.get("ADAPTIVE", "1") != "0"
NVENC_DELAY = os.environ.get("NVENC_DELAY", "0")   # frames que NVENC puede retener antes de entregar ("" = valor de ffmpeg)

# Reloj del servidor para medir latencias (ms de época): perf_counter (QPC, sub-ms) anclado a time.time(), que en
# Windows tiene resolución de 15,6 ms. Los frames llevan este reloj en `ts` y el visor lo sincroniza con ping/pong.
_CLOCK0 = time.time() - time.perf_counter()


def now_ms():
    return (time.perf_counter() + _CLOCK0) * 1000.0


def pct(samples, p):
    """Percentil p (0..100) de una secuencia, o None si está vacía."""
    s = sorted(samples)
    return round(s[min(len(s) - 1, int(len(s) * p / 100))], 1) if s else None


state = {"ipads": set(), "status": set()}
input_lat = deque(maxlen=300)   # latencia de input en ms: reloj del servidor al inyectar - "t" que estampó el visor
mouse = Mouse()
pen = Pen(mouse)
log = logging.getLogger("bridge")
pool = ThreadPoolExecutor(max_workers=2)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def http_url(path, host=None):
    host = host or local_ip()
    return f"http://{host}{'' if PORT == 80 else ':' + str(PORT)}{path}"


def https_url(path, host=None):
    host = host or local_ip()
    return f"https://{host}{'' if TLS_PORT == 443 else ':' + str(TLS_PORT)}{path}"


def target_info():
    t = target_display()
    l, tp, r, b = t["rect"]
    return {"name": t["name"], "width": r - l, "height": b - tp, "virtual": t["virtual"], "hz": min(MAX_FPS, t.get("hz", 60))}


def wanted_bitrate():
    """100 Mbps si todos los visores van por USB; si alguno va por red, 50."""
    transports = {getattr(w, "_transport", "net") for w in state["ipads"]}
    return BITRATE_USB if transports and transports <= {"usb"} else BITRATE_NET


# ---------------------------------------------------------------- calidad adaptativa (ítem 1.7 del plan)

class Quality:
    """Decide escala de captura, factor de bitrate y tope de fps según lo que miden los visores (cola de decodificación,
    descartes, RTT del ping y fps recibidos, que llegan en cada ping/stats) y el preset manual del iPad.
    Un solo encoder sirve a todos los visores, así que manda el que peor va. Cada cambio reinicia ffmpeg (~0,3 s de
    congelación), por eso hay histéresis: baja tras 2 ticks malos seguidos (4 s) y como mucho cada 8 s; sube tras 30 s
    estables. Por USB solo cuenta la cola del decodificador (no hay red que sufra).
    Escalas: 100/75/50 % del monitor. Modos: auto = primero bitrate, después escala; draw (mejor para dibujar) = nunca
    baja la escala, sacrifica bitrate y fps; motion (mejor para movimiento) = nunca baja los fps, sacrifica escala."""

    LADDERS = {
        "auto":   [dict(scale=1.0, br=1.0, fps=None), dict(scale=1.0, br=0.6, fps=None), dict(scale=0.75, br=0.45, fps=None), dict(scale=0.5, br=0.3, fps=None)],
        "draw":   [dict(scale=1.0, br=1.0, fps=None), dict(scale=1.0, br=0.7, fps=None), dict(scale=1.0, br=0.5, fps=30), dict(scale=1.0, br=0.35, fps=30)],
        "motion": [dict(scale=1.0, br=1.0, fps=None), dict(scale=0.75, br=0.6, fps=None), dict(scale=0.5, br=0.35, fps=None), dict(scale=0.5, br=0.25, fps=None)],
    }
    STEP_DOWN_TICKS, STEP_UP_TICKS, COOLDOWN = 2, 15, 8.0   # ticks de 2 s (status_loop)

    def __init__(self):
        self.mode, self.level = "auto", 0
        self.bad = self.good = 0
        self.changed_at = 0.0
        self.reason = ""

    def set_mode(self, mode):
        if mode not in self.LADDERS:
            raise ValueError(f"modo de calidad desconocido: {mode}")
        if mode != self.mode:
            log.info("calidad: modo %s (antes %s)", mode, self.mode)
            self.mode, self.level, self.bad, self.good = mode, 0, 0, 0

    def current(self):
        return self.LADDERS[self.mode][self.level]

    def info(self):
        c = self.current()
        return {"mode": self.mode, "level": self.level, "scale": c["scale"], "br": c["br"], "fps_cap": c["fps"], "reason": self.reason}

    @staticmethod
    def viewer_trouble(w, capture_fps):
        """Qué sufre un visor según sus últimos pings/stats, o '' si va bien."""
        q, drops = getattr(w, "_q", 0), getattr(w, "_drops", 0)
        if q >= 4:
            return f"cola {q}"
        if drops:
            return f"descartes {drops}"
        if getattr(w, "_transport", "net") == "usb":
            return ""
        rtts = list(getattr(w, "_rtt", ()))   # deque: no admite rebanadas (esto mataba el bucle de estado a los 8 s)
        if len(rtts) >= 4 and min(rtts[-2:]) > min(rtts) + 40:
            return f"rtt {rtts[-1]:.0f} ms (base {min(rtts):.0f})"
        st = getattr(w, "_stats", None)
        if st and capture_fps and st.get("fps") is not None and st["fps"] < 0.75 * capture_fps and now_ms() - st.get("_at", 0) < 8000:
            return f"fps {st['fps']} de {capture_fps}"
        return ""

    def tick(self, viewers, capture_fps):
        """Cada 2 s desde status_loop. Devuelve True si cambió el nivel (hay que reiniciar la captura)."""
        if not ADAPTIVE or not viewers:
            return False
        troubles = [t for t in (self.viewer_trouble(w, capture_fps) for w in viewers) if t]
        now = time.monotonic()
        ladder = self.LADDERS[self.mode]
        if troubles:
            self.bad, self.good = self.bad + 1, 0
            if self.bad >= self.STEP_DOWN_TICKS and self.level < len(ladder) - 1 and now - self.changed_at >= self.COOLDOWN:
                self.level, self.bad, self.changed_at, self.reason = self.level + 1, 0, now, troubles[0]
                log.info("calidad: bajo a nivel %d (%s) por %s", self.level, ladder[self.level], troubles[0])
                return True
        else:
            self.bad, self.good = 0, self.good + 1
            if self.good >= self.STEP_UP_TICKS and self.level > 0:
                self.level, self.good, self.changed_at, self.reason = self.level - 1, 0, now, "estable"
                log.info("calidad: subo a nivel %d (%s): 30 s estable", self.level, ladder[self.level])
                return True
        return False


quality = Quality()


async def find_output(width, height):
    """Índice de salida DXGI cuyo tamaño coincide con el monitor objetivo (ddagrab enumera salidas del adaptador)."""
    for idx in range(4):
        p = await asyncio.create_subprocess_exec(
            FFMPEG, "-hide_banner", "-filter_complex", f"ddagrab=output_idx={idx}:framerate=5",
            "-frames:v", "1", "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await p.communicate()
        m = re.search(r"Stream #0:0.*?(\d{3,5})x(\d{3,5})", err.decode(errors="replace"))
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            log.info("ddagrab salida %d = %dx%d", idx, w, h)
            if abs(w - width) <= 2 and abs(h - height) <= 2:
                return idx
        elif idx > 0:
            break
    return None


# ---------------------------------------------------------------- video HEVC 10 bits

class Capture:
    """ffmpeg: ddagrab (Desktop Duplication, en GPU) -> hevc_nvenc Main10 -> Annex B por stdout.
    Convierte cada access unit a muestras con largo de 4 bytes y las reparte a los visores."""

    def __init__(self):
        self.proc = None
        self.task = None
        self.vps = self.sps = self.pps = None
        self.config_msg = None
        self.frames = 0
        self.bytes = 0
        self.started_at = None
        self.output_idx = None
        self.fps = 60
        self.bitrate = BITRATE_NET
        self.scale = 1.0
        self.width = self.height = 0      # tamaño codificado (el monitor por la escala)
        self.last_key_at = 0.0            # monotonic del último IDR emitido
        self.restarting = False

    def wanted(self):
        """(bitrate, fps, escala) que corresponde ahora: transporte de los visores, refresco del monitor y calidad."""
        q, t = quality.current(), target_info()
        fps = min(t["hz"], q["fps"]) if q["fps"] else t["hz"]
        return max(5, round(wanted_bitrate() * q["br"])), fps, q["scale"]

    async def start(self):
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def restart_if_needed(self):
        """Reinicia ffmpeg si cambió el bitrate deseado (p. ej. un visor pasó de Wi-Fi a USB) o el refresco del monitor."""
        if self.proc is None or self.task is None or self.task.done():
            return
        br, fps, scale = self.wanted()
        if (br, fps, scale) != (self.bitrate, self.fps, self.scale):
            log.info("reiniciando captura: %d Mbps @ %d fps, escala %d %%", br, fps, scale * 100)
            await self.restart()

    async def restart(self):
        """Reinicia ffmpeg conservando la salida DXGI ya encontrada (sin volver a sondear: ~0,5 s en vez de ~1,5)."""
        if self.restarting:
            return
        self.restarting = True
        try:
            await self.stop()
            await self.start()
        finally:
            self.restarting = False

    async def request_key(self):
        """need-key de un visor: con intra-refresh no hay más IDR que el primero, así que se reinicia el encoder.
        Se ignora si el último IDR salió hace menos de 1 s (el visor acaba de conectarse y ya lo tiene o está en camino)."""
        if KEYFRAMES != "refresh" or self.proc is None or self.task is None or self.task.done():
            return
        now = time.monotonic()
        # Encoder recién arrancado (su IDR inicial viene en camino) o IDR reciente: no reiniciar de nuevo. También frena
        # a un visor que pide keyframes en cadena (p. ej. una pestaña en segundo plano que no da abasto).
        # Mínimo 2,5 s entre IDR: cada reinicio congela ~0,3 s y manda un IDR grande que por Wi-Fi llena la cola del
        # decodificador, lo que hacía que el visor pidiera otro keyframe enseguida (medido: 30 reinicios en 2 minutos).
        if now - self.started_at < 1.5 or now - self.last_key_at < 2.5 or self.restarting:
            return
        log.info("need-key: reinicio del encoder para emitir un IDR")
        await self.restart()

    async def _run(self):
        while True:
            t = target_info()
            idx = self.output_idx if self.output_idx is not None else await find_output(t["width"], t["height"])
            if idx is None:
                log.error("no encuentro la salida DXGI del monitor %s (%dx%d); reintento en 5 s", t["name"], t["width"], t["height"])
                await asyncio.sleep(5)
                continue
            self.output_idx = idx
            self.bitrate, self.fps, self.scale = self.wanted()
            fps, br, scale = self.fps, self.bitrate, self.scale
            self.width, self.height = (t["width"], t["height"]) if scale == 1 else (int(t["width"] * scale) & ~1, int(t["height"] * scale) & ~1)
            graph = f"ddagrab=output_idx={idx}:framerate={fps}"
            if scale != 1:
                # Escala reducida (calidad adaptativa). Este ffmpeg no mapea D3D11->CUDA ni le anda scale_d3d11 (falla al
                # crear la textura, medido con 8.1), así que el frame baja a RAM y vuelve a CUDA: 2560x1440 a 60 fps
                # sostenidos (medido), ~0,9 GB/s de PCIe y un hilo; solo se usa cuando un visor por red sufre.
                graph += f",hwdownload,format=bgra,hwupload_cuda,scale_cuda=w={self.width}:h={self.height}"
            gop = max(1, round(fps * GOP_S))
            args = [FFMPEG, "-hide_banner", "-loglevel", "error",
                    "-filter_complex", graph,
                    # HEVC Main10 desde RGB de 8 bits (highbitdepth): menos banding y ~40% menos bits que H.264.
                    # NVENC convierte RGB->YUV con BT.601 y lo declara en el VUI (medido: coincide con la captura).
                    "-c:v", "hevc_nvenc", "-preset", "p4", "-tune", "ll", "-zerolatency", "1",
                    # -delay 0: entregar cada frame apenas codificado; por defecto NVENC retiene frames en su cola
                    # asíncrona (medido con tools/latency_clock.py, ver README). NVENC_DELAY="" deja el valor de ffmpeg.
                    *(["-delay", NVENC_DELAY] if NVENC_DELAY else []),
                    "-rc", "cbr", "-b:v", f"{br}M", "-maxrate", f"{br}M", "-bufsize", f"{max(1, br // 4)}M",
                    "-profile:v", "main10", "-highbitdepth", "1", "-spatial-aq", "1", "-aq-strength", "8",
                    "-g", str(gop), "-bf", "0", "-aud", "1"]
            if KEYFRAMES == "refresh":
                # Intra-refresh: GOP infinito tras el IDR inicial, con una onda de columnas intra cada `gop` frames.
                args += ["-intra-refresh", "1"]
            args += ["-f", "hevc", "-"]
            log.info("captura: %s %dx%d @ %d fps (salida %d) -> NVENC HEVC 10b %d Mbps, %s, GOP %d", t["name"], self.width, self.height,
                     fps, idx, br, "intra-refresh" if KEYFRAMES == "refresh" else "IDR", gop)
            self.proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self.started_at = time.monotonic()
            self.vps = self.sps = self.pps = None   # config_msg se conserva: solo se reenvía si cambia
            try:
                await self._pump(self.proc.stdout)
            except asyncio.CancelledError:
                self._kill()
                raise
            err = (await self.proc.stderr.read()).decode(errors="replace").strip()
            log.error("ffmpeg terminó (%s): %s", self.proc.returncode, err[-400:])
            self.proc = None
            self.output_idx = None    # volver a sondear por si cambió la disposición de monitores
            await asyncio.sleep(2)

    def _kill(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.proc = None

    async def _pump(self, stream):
        buf = b""
        au, key = [], False
        start = re.compile(rb"\x00\x00\x01")
        while True:
            chunk = await stream.read(256 * 1024)
            if not chunk:
                return
            buf += chunk
            positions = [m.start() for m in start.finditer(buf)]
            if len(positions) < 2:
                continue
            for i in range(len(positions) - 1):
                s, e = positions[i] + 3, positions[i + 1]
                if e > 0 and buf[e - 1] == 0:   # start code de 4 bytes
                    e -= 1
                nal = buf[s:e]
                if len(nal) < 2:
                    continue
                t = hevc.nal_type(nal)
                if t == hevc.AUD:
                    if au:
                        await self._emit(au, key)
                    au, key = [], False
                elif t in (hevc.VPS, hevc.SPS, hevc.PPS):
                    attr = {hevc.VPS: "vps", hevc.SPS: "sps", hevc.PPS: "pps"}[t]
                    if getattr(self, attr) != nal:
                        setattr(self, attr, nal)
                        self._update_config()
                else:
                    if hevc.is_irap(t):
                        key = True
                    au.append(nal)
            buf = buf[positions[-1]:]

    def _update_config(self):
        if not (self.vps and self.sps and self.pps):
            return
        rec, s = hevc.build_hvcc(self.vps, self.sps, self.pps)
        msg = {"type": "vconfig", "codec": hevc.codec_string(s), "width": self.width, "height": self.height,
               "description": base64.b64encode(rec).decode()}
        if msg == self.config_msg:
            return   # reinicio del encoder con los mismos parámetros (need-key): los visores no tienen que reconfigurar
        self.config_msg = msg
        log.info("config %s %dx%d %d bits", msg["codec"], self.width, self.height, s["bit_depth_luma"])
        asyncio.create_task(send_ipads(self.config_msg))

    async def _emit(self, nals, key):
        if not self.config_msg:
            return
        payload = b"".join(struct.pack(">I", len(n)) + n for n in nals)
        # ts: reloj del servidor (ms de época) al salir del encoder. No es el instante de captura: ddagrab + NVENC quedan
        # fuera (medido con un reloj en pantalla: ver README, "Cómo leer el HUD").
        ts = now_ms()
        if key:
            self.last_key_at = time.monotonic()
        self.frames += 1
        self.bytes += len(payload)
        await send_ipads(data=struct.pack(">Bd", 1 if key else 0, ts) + payload)


# ---------------------------------------------------------------- imagen fija sin pérdida

class StillWatcher:
    """Segundo ddagrab con dup_frames=0: solo entrega frames cuando el escritorio cambia. Si pasan STILL_AFTER s sin
    cambios, manda el último frame como PNG (los píxeles exactos de Windows). Al primer cambio manda still-clear."""

    def __init__(self):
        self.task = None
        self.proc = None
        self.current_png = None   # PNG vigente (pantalla quieta) o None
        self.sent = 0

    async def start(self, output_idx):
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self._run(output_idx))

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        self.current_png = None

    async def _run(self, idx):
        t = target_info()
        w, h = t["width"], t["height"]
        frame_size = w * h * 4
        # ddagrab entrega frames aunque no cambie nada; la quietud se detecta comparando bytes (memcmp, ~2 ms).
        # 10 fps: detecta el cambio en 100 ms y la lectura GPU->CPU queda en ~220 MB/s.
        args = [FFMPEG, "-hide_banner", "-loglevel", "error",
                "-filter_complex", f"ddagrab=output_idx={idx}:framerate=10,hwdownload,format=bgra",
                "-f", "rawvideo", "-pix_fmt", "bgra", "-"]
        while True:
            self.proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                             stderr=asyncio.subprocess.DEVNULL, limit=frame_size * 2)
            last, changed_t, sent_for_last, last_sent_t = None, time.monotonic(), True, 0.0
            log.info("imagen fija: vigilando cambios del escritorio (salida %d)", idx)
            try:
                while True:
                    try:
                        frame = await asyncio.wait_for(self.proc.stdout.readexactly(frame_size), timeout=0.2)
                    except asyncio.TimeoutError:
                        frame = None
                    except asyncio.IncompleteReadError:
                        break
                    now = time.monotonic()
                    if frame is not None and frame != last:
                        last, changed_t, sent_for_last = frame, now, False
                        if self.current_png is not None:
                            self.current_png = None
                            await send_ipads({"type": "still-clear"})
                    # Un cursor parpadeando alterna dos estados: limitar a una imagen fija por segundo.
                    if last is not None and not sent_for_last and now - changed_t >= STILL_AFTER and now - last_sent_t >= 1.0:
                        sent_for_last, last_sent_t = True, now
                        t0 = time.monotonic()
                        png = await asyncio.get_running_loop().run_in_executor(pool, encode_png, last, w, h)
                        self.current_png = png
                        self.sent += 1
                        log.info("imagen fija enviada: %.1f MB (png %d ms)", len(png) / 1e6, (time.monotonic() - t0) * 1000)
                        await send_ipads(data=b"" + png)
            except asyncio.CancelledError:
                self._kill()
                raise
            self._kill()
            log.error("ddagrab de imagen fija terminó; reintento en 2 s")
            await asyncio.sleep(2)

    def _kill(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.proc = None


def encode_png(bgra, w, h):
    from PIL import Image
    img = Image.frombuffer("RGBA", (w, h), bgra, "raw", "BGRA", 0, 1).convert("RGB")
    out = io.BytesIO()
    img.save(out, "PNG", compress_level=1)   # nivel 1: rápido; el tamaño importa menos por USB
    return out.getvalue()


capture = Capture()
stills = StillWatcher()


# ---------------------------------------------------------------- websocket

async def send(ws, obj):
    if ws is not None and not ws.closed:
        await ws.send_str(json.dumps(obj))


async def send_ipads(obj=None, data=None):
    for w in list(state["ipads"]):
        if w.closed:
            state["ipads"].discard(w)
            continue
        try:
            if data is not None:
                await w.send_bytes(data)
            else:
                await w.send_str(json.dumps(obj))
        except (ConnectionResetError, RuntimeError):
            state["ipads"].discard(w)


def _tilt(m):
    """Inclinación: 'tx'/'ty' en grados (Safari) o 'alt'/'az' en radianes (UIKit)."""
    if "tx" in m or "ty" in m:
        return int(m.get("tx", 0)), int(m.get("ty", 0))
    if "alt" in m:
        return tilt_from_angles(m.get("alt"), m.get("az", 0))
    return 0, 0


_pen_deferred = []      # eventos del Pencil en espera mientras el lápiz entra en alcance (PEN_ARM_MS)
_pen_arming = False


def _pen_flush():
    global _pen_arming
    _pen_arming = False
    queued, _pen_deferred[:] = list(_pen_deferred), []
    for q in queued:
        handle_pen(q)


def handle_pen(m):
    """Eventos del Pencil ("pen":1) -> lápiz virtual con presión. Si no hay lápiz (Windows viejo), mouse izquierdo."""
    global _pen_arming
    ev = m.get("ev")
    if _pen_arming and ev != "pencfg":
        _pen_deferred.append(m)
        return
    if not pen.available:
        m.pop("pen", None)
        if ev == "moves":
            x, y = m["pts"][-1][:2]
            return handle_mouse({"ev": "move", "x": x, "y": y})
        if ev in ("move", "down", "up"):
            return handle_mouse(m)
        return
    if ev == "moves":
        pts = m["pts"]
        # Los puntos coalescidos no traen hora: repartirlos entre el evento anterior y ahora (para el filtro 1€).
        now = time.monotonic()
        t0 = max(pen.last, now - 0.1)
        for i, pt in enumerate(pts):        # trayectoria completa (toques coalescidos, hasta 240 Hz)
            x, y, p = pt[0], pt[1], pt[2] if len(pt) > 2 else None
            tx, ty = (int(pt[3]), int(pt[4])) if len(pt) > 4 else (0, 0)
            pen.move(x, y, p, tx, ty, t0 + (now - t0) * (i + 1) / len(pts))
    elif ev == "move":
        pen.move(m["x"], m["y"], m.get("p"), *_tilt(m))
    elif ev == "pencfg":
        # Curva de presión y suavizado desde el panel del iPad; se aplica en caliente, sin reiniciar.
        pen.configure(gamma=m.get("gamma"), min_pressure=m.get("min"), smooth=m.get("smooth"))
    elif ev == "hover":
        pen.hover(m["x"], m["y"], *_tilt(m))
    elif ev == "down":
        if not pen.inrange and PEN_ARM_MS > 0:
            # Entrar en alcance ahora y tocar PEN_ARM_MS después, como un lápiz real; lo que llegue mientras tanto
            # (este down incluido) se reproduce en orden cuando vence el plazo.
            pen.hover(m["x"], m["y"], *_tilt(m))
            _pen_arming = True
            _pen_deferred.append(m)
            asyncio.get_running_loop().call_later(PEN_ARM_MS / 1000, _pen_flush)
            return
        pen.set_barrel(m.get("btn") == 2)
        pen.down(m["x"], m["y"], m.get("p", 0), *_tilt(m))
    elif ev == "up":
        pen.up(m["x"], m["y"], *_tilt(m))
        pen.set_barrel(False)
        # iPad sin hover: no va a avisar que el lápiz se alejó. Si no llega nada más, salir de alcance.
        asyncio.get_running_loop().call_later(PEN_LEAVE_S, pen.leave_if_idle, pen.last)
    elif ev == "leave":
        pen.leave()
    elif ev == "eraser":
        try:
            tap_keys(PEN_TAP_KEYS[0] if m.get("on") else PEN_TAP_KEYS[-1])
        except ValueError as e:
            log.warning("PEN_TAP_KEYS: %s", e)
    elif ev == "barrel":
        pen.set_barrel(m.get("on"))


def handle_mouse(m):
    ev = m.get("ev")
    if pen.contact:
        return                               # la palma o un dedo mientras se dibuja: ignorar, como un Cintiq con touch apagado
    if ev == "move":
        mouse.move(m["x"], m["y"])
    elif ev == "down":
        if "x" in m:                         # sin coordenadas: botón en la posición actual del cursor (barra)
            mouse.move(m["x"], m["y"])
        mouse.down(int(m.get("btn", 0)))
    elif ev == "up":
        if "x" in m:
            mouse.move(m["x"], m["y"])
        mouse.up(int(m.get("btn", 0)))
    elif ev == "scroll":
        mouse.scroll(dy=m.get("dy", 0), dx=m.get("dx", 0))


MOD_KEYS = ("shift", "ctrl", "alt", "space", "win")


def handle_keys(m):
    """Barra lateral de teclas (estilo ExpressKeys): {"ev":"key","keys":"ctrl+z"} pulsa un atajo;
    {"ev":"mod","key":"shift","down":true|false} mantiene un modificador mientras se toca el botón;
    {"ev":"text","text":"hola"} escribe texto tal cual (teclado en pantalla del iPad).
    Van antes que handle_mouse: se usan justamente mientras el Pencil está en contacto."""
    ev = m.get("ev")
    try:
        if ev == "key":
            tap_keys(str(m.get("keys", "")))
        elif ev == "text":
            type_text(str(m.get("text", ""))[:200])
        elif ev == "mod":
            key = str(m.get("key", "")).lower()
            if key not in MOD_KEYS:
                raise ValueError(f"modificador desconocido: {key}")
            hold_key(key, bool(m.get("down")))
    except ValueError as e:
        log.warning("barra de teclas: %s", e)


def handle_input(m):
    ev = m.get("ev")
    if ev in ("key", "mod", "text"):
        handle_keys(m)
    elif m.get("pen") or ev == "pencfg":
        handle_pen(m)
    else:
        handle_mouse(m)


# ---------------------------------------------------------------- ventana activa -> perfil de la barra del iPad

app_state = {"exe": "", "title": ""}


def app_msg():
    return {"type": "app", "exe": app_state["exe"], "title": app_state["title"]}


async def app_loop():
    """Cada 0.5 s mira la ventana activa de Windows; si cambió el ejecutable manda {"type":"app"} a los visores,
    que eligen el perfil de la barra de atajos (shortcuts.json)."""
    while True:
        await asyncio.sleep(0.5)
        if not state["ipads"]:
            continue
        try:
            exe, title = foreground_app()
            if not exe:                      # sin ventana activa (escritorio, bloqueo): dejar el perfil que estaba
                continue
            if exe != app_state["exe"]:
                app_state.update(exe=exe, title=title)
                log.info("app activa: %s (%s)", exe, title[:60])
                await send_ipads(app_msg())
        except asyncio.CancelledError:
            raise
        except Exception:                    # OSError de Windows o un visor caído: no matar el bucle
            log.exception("app_loop: error (sigo)")


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=10, max_msg_size=64 * 1024 * 1024)
    await ws.prepare(request)
    role = None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            t = m.get("type")
            if t == "hello":
                role = "ipad" if m.get("role") == "ipad" else "status"
                ws._transport = m.get("transport", "net")  # la app por usb_bridge dice "usb" o "net"; Safari no dice nada = red
                ws._rtt, ws._q, ws._drops, ws._stats = deque(maxlen=30), 0, 0, None   # medición (ping/stats del visor)
                state["ipads" if role == "ipad" else "status"].add(ws)
                log.info("%s conectado desde %s por %s (visores: %d)", role, request.remote, ws._transport, len(state["ipads"]))
                if role == "ipad":
                    await capture.restart_if_needed()
                    await capture.start()
                    if capture.config_msg:
                        await send(ws, capture.config_msg)
                    if stills.current_png is not None:
                        await ws.send_bytes(b"\x02" + stills.current_png)
                    try:                      # perfil de la barra: la ventana activa ahora mismo
                        exe, title = foreground_app()
                        if exe:
                            app_state.update(exe=exe, title=title)
                    except OSError:
                        pass
                    if app_state["exe"]:
                        await send(ws, app_msg())
                else:
                    await send(ws, {"type": "info", "ipad_url": https_url("/ipad.html"), "setup_url": http_url("/"),
                                    "target": target_info()})
            elif t == "input":
                handle_input(m)
                if "t" in m:   # el visor estampa el evento con el reloj del servidor estimado: latencia hasta inyectar
                    input_lat.append(now_ms() - float(m["t"]))
            elif t == "ping" and role:
                # Sincronización de reloj estilo NTP: devolvemos su t y nuestro reloj; el visor calcula RTT y offset.
                # De paso trae cola del decodificador (q), descartes desde el último ping (d) y su último RTT.
                ws._q, ws._drops = int(m.get("q", 0)), int(m.get("d", 0))
                if m.get("rtt") is not None:
                    ws._rtt.append(float(m["rtt"]))
                await send(ws, {"type": "pong", "t": m.get("t"), "mt": now_ms(), "inp50": pct(input_lat, 50), "inp95": pct(input_lat, 95),
                                "br": capture.bitrate, "scale": capture.scale, "fps": capture.fps, "mode": quality.mode, "level": quality.level})
            elif t == "stats":
                ws._stats = dict(m, _at=now_ms(), transport=m.get("transport", ws._transport), remote=request.remote)
                log.info("stats %s: %s", request.remote, " ".join(f"{k}={v}" for k, v in m.items() if k != "type"))
            elif t == "quality":
                try:
                    quality.set_mode(str(m.get("mode", "auto")))
                    await capture.restart_if_needed()
                except ValueError as e:
                    log.warning("calidad: %s", e)
            elif t == "need-key":
                # Con KEYFRAMES=idr el visor espera al próximo IDR (uno por segundo); con intra-refresh se reinicia el encoder.
                await capture.request_key()
    finally:
        if role:
            state["ipads" if role == "ipad" else "status"].discard(ws)
        if role == "ipad":
            mouse.release_all()
            pen.release_all()
            release_keys()      # modificadores de la barra lateral que quedaron mantenidos
            if not state["ipads"]:
                await capture.stop()
                await stills.stop()
                log.info("sin visores: captura detenida")
        log.info("%s desconectado", role)
    return ws


async def status_loop():
    """Cada 2 s: arranca el detector de pantalla quieta cuando hay captura, revisa cambios y manda estado."""
    last_f, last_b, last_t = 0, 0, time.monotonic()
    while True:
        await asyncio.sleep(2)
        # Nada de lo que pase acá puede matar el bucle: de él dependen la calidad adaptativa, el detector de imagen
        # fija y pc.html. (Medido: una excepción no capturada lo mataba en silencio y el iPad quedaba clavado en el
        # nivel de calidad del momento, sin imagen fija y sin datos en pc.html.)
        try:
            now = time.monotonic()
            dt = now - last_t
            fps = (capture.frames - last_f) / dt
            mbps = (capture.bytes - last_b) * 8 / dt / 1e6
            last_f, last_b, last_t = capture.frames, capture.bytes, now
            if state["ipads"]:
                quality.tick(list(state["ipads"]), capture.fps if capture.proc else 0)
                await capture.restart_if_needed()  # cambió el refresco del monitor, el transporte de un visor o la calidad
                if capture.proc is not None and capture.output_idx is not None:
                    await stills.start(capture.output_idx)
            st = {"type": "status", "viewers": len(state["ipads"]), "capturing": capture.proc is not None,
                  "fps": round(fps), "mbps": round(mbps, 1), "target": target_info(), "bitrate": capture.bitrate,
                  "still": stills.current_png is not None, "stills_sent": stills.sent,
                  "transports": sorted({getattr(w, "_transport", "net") for w in state["ipads"]}),
                  "quality": dict(quality.info(), width=capture.width, height=capture.height, fps=capture.fps, keyframes=KEYFRAMES),
                  "input_ms": {"p50": pct(input_lat, 50), "p95": pct(input_lat, 95)},
                  "viewer_stats": [getattr(w, "_stats", None) for w in state["ipads"] if getattr(w, "_stats", None)]}
            for w in list(state["status"]):
                try:
                    await send(w, st)
                except (ConnectionResetError, RuntimeError):   # pc.html se cerró entre el chequeo y el envío
                    state["status"].discard(w)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("status_loop: error en un tick (sigo)")


# ---------------------------------------------------------------- http

async def index(request):
    if request.host.split(":")[0] in ("localhost", "127.0.0.1"):
        raise web.HTTPFound("/pc.html")
    html = (STATIC / "setup.html").read_text(encoding="utf-8")
    html = (html.replace("{{HTTPS}}", https_url("")).replace("{{HTTP}}", http_url(""))
                .replace("{{IP}}", local_ip()).replace("{{PORT}}", str(PORT)).replace("{{TLS_PORT}}", str(TLS_PORT)))
    return web.Response(text=html, content_type="text/html")


async def ca_cert(request):
    return web.Response(body=(CERTS / "ca.crt").read_bytes(), content_type="application/x-x509-ca-cert")


async def ping(request):
    return web.json_response({"ok": True, "scheme": request.scheme, "host": request.host, "remote": request.remote},
                             headers={"Access-Control-Allow-Origin": "*"})


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/ca.crt", ca_cert)
app.router.add_get("/ping", ping)
app.router.add_get("/ws", ws_handler)
app.router.add_static("/", STATIC, show_index=False)


async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    tls = None
    if (CERTS / "server.crt").exists():
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(CERTS / "server.crt", CERTS / "server.key")
        await web.TCPSite(runner, "0.0.0.0", TLS_PORT, ssl_context=tls).start()
    t = target_info()
    print("=" * 60)
    print(f"  Estado (PC):      {http_url('/', 'localhost')}")
    print(f"  iPad (1ª vez):    {http_url('/')}   <- instalar certificado")
    print(f"  iPad (pantalla):  {https_url('/ipad.html') if tls else http_url('/ipad.html')}")
    print(f"  Monitor objetivo: {t['name']} {t['width']}x{t['height']} @ {t['hz']} Hz ({'virtual' if t['virtual'] else 'SIN monitor virtual: espejo'})")
    print(f"  Pencil:           {'lápiz virtual con presión (gamma %.2f, suavizado %.1f; el iPad los cambia desde su panel)' % (pen.gamma, pen.smooth) if pen.available else 'mouse (sin presión: Windows sin pointer injection)'}")
    print("=" * 60, flush=True)
    def _watch(task):
        """Si un bucle de fondo termina igual, que quede en el log con su traceback (y no solo al recolectar la tarea)."""
        if not task.cancelled() and task.exception() is not None:
            log.error("tarea %s terminó con error", task.get_name(), exc_info=task.exception())
    app["bg"] = [asyncio.create_task(status_loop(), name="status_loop"), asyncio.create_task(app_loop(), name="app_loop")]
    for task in app["bg"]:
        task.add_done_callback(_watch)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    # Consola y server.log (rotativo, 5 MB x 3) en la carpeta del proyecto: las stats del iPad y cualquier error quedan
    # para diagnosticar después sin estar mirando la ventana.
    from logging.handlers import RotatingFileHandler
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(Path(__file__).parent / "server.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), file_handler])
    for h in logging.getLogger().handlers:
        h.setFormatter(fmt)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    asyncio.run(main())
