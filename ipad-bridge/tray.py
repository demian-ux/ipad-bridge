"""iPad Bridge en la bandeja del sistema: arranca el servidor y el puente (lo que hacía start.ps1), muestra el estado
(sin iPad / por USB / por red, fps, Mbps, visores) y ofrece lo de todos los días: abrir el panel, los logs, la IP de
respaldo, iniciar con Windows, reiniciar o salir. Al salir mata a los hijos (y si la bandeja muere, Windows los mata
igual: van en un job object con KILL_ON_JOB_CLOSE).

Uso:  pythonw tray.py [IP del iPad] [--port 80] [--tls-port 443]
Desarrollo: desde la carpeta del proyecto, con el Python del sistema (datos, logs y certificados en esta carpeta).
Instalado: el instalador lo lanza con el Python embebido de {app}\\python; datos en %LOCALAPPDATA%\\iPad Bridge
(IPAD_BRIDGE_DATA lo cambia). El estado llega por el mismo WebSocket que usa pc.html (hello role=status).
"""
import asyncio
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
INSTALLED = (ROOT / "python" / "python.exe").exists()          # instalado con el instalador: runtime embebido al lado
DATA = Path(os.environ.get("IPAD_BRIDGE_DATA") or (Path(os.environ["LOCALAPPDATA"]) / "iPad Bridge" if INSTALLED else ROOT))
PYTHON = ROOT / "python" / "python.exe" if INSTALLED else Path(sys.executable).with_name("python.exe")
PYTHONW = PYTHON.with_name("pythonw.exe")
FFMPEG = ROOT / "ffmpeg" / "ffmpeg.exe"
CONFIG = DATA / "config.json"
STARTUP_LNK = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "iPad Bridge.lnk"
USBMUX_PORT = 27015         # servicio Apple Mobile Device (app "Dispositivos Apple"): sin él no hay iPad por USB
CREATE_NO_WINDOW = 0x08000000

log = logging.getLogger("tray")


# ---------------------------------------------------------------- job object: los hijos mueren con la bandeja

class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                  "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def make_job():
    """Job object que mata a todos sus procesos (servidor, puente y los ffmpeg que lance el servidor) al cerrarse el
    último handle, es decir, cuando muere la bandeja por la razón que sea."""
    k32 = ctypes.windll.kernel32
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # JobObjectExtendedLimitInformation
        return None
    return job


def single_instance():
    """True si somos la única bandeja (mutex con nombre; el handle queda vivo hasta que el proceso termina)."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\iPadBridgeTray")
    return ctypes.windll.kernel32.GetLastError() != 183      # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- icono

COLORS = {"off": (150, 150, 150), "usb": (70, 200, 110), "net": (80, 160, 255), "down": (230, 80, 70)}


def icon_image(state="off", size=64):
    """Tableta con la pantalla y un punto de estado: gris sin iPad, verde por USB, azul por red, rojo servidor caído."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle((6 * s, 4 * s, 58 * s, 60 * s), radius=8 * s, fill=(240, 240, 240), outline=(60, 60, 60), width=int(3 * s))
    d.rectangle((12 * s, 10 * s, 52 * s, 50 * s), fill=(40, 44, 52))
    d.ellipse((29 * s, 52 * s, 35 * s, 58 * s), fill=(60, 60, 60))                       # botón home
    c = COLORS[state]
    d.ellipse((40 * s, 36 * s, 62 * s, 58 * s), fill=c, outline=(255, 255, 255), width=int(3 * s))
    return img


def write_ico(path):
    """Icono .ico para el instalador y los accesos directos (lo usa installer/build.ps1)."""
    icon_image("usb", 256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


# ---------------------------------------------------------------- configuración

def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def input_box(title, prompt, default=""):
    """Cuadro de texto simple sin tkinter (el Python embebido no lo trae): InputBox de Visual Basic vía PowerShell.
    Devuelve None si se canceló."""
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; "
          "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          "$r=[Microsoft.VisualBasic.Interaction]::InputBox($args[0],$args[1],$args[2]); "
          "if($r -eq ''){exit 2}; Write-Output $r")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps, prompt, title, default],
                       capture_output=True, text=True, encoding="utf-8", creationflags=CREATE_NO_WINDOW)
    return None if r.returncode == 2 else r.stdout.strip()


def message_box(text, title="iPad Bridge", flags=0x40):
    ctypes.windll.user32.MessageBoxW(None, text, title, flags)


# ---------------------------------------------------------------- iniciar con Windows (acceso directo en Inicio)

def startup_enabled():
    return STARTUP_LNK.exists()


def set_startup(on):
    if not on:
        try:
            STARTUP_LNK.unlink()
        except FileNotFoundError:
            pass
        return
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); $s.TargetPath=$args[1]; "
          "$s.Arguments=$args[2]; $s.WorkingDirectory=$args[3]; $s.IconLocation=$args[4]; $s.Description='iPad Bridge'; $s.Save()")
    ico = ROOT / "ipad-bridge.ico"
    subprocess.run(["powershell", "-NoProfile", "-Command", ps, str(STARTUP_LNK), str(PYTHONW), f'"{ROOT / "tray.py"}"',
                    str(ROOT), str(ico) if ico.exists() else str(PYTHONW)], creationflags=CREATE_NO_WINDOW, check=False)


# ---------------------------------------------------------------- procesos

class Bridge:
    """Servidor + puente, como start.ps1: certificados para la IP actual, server.py en 80/443, usb_bridge.py en modo auto."""

    def __init__(self, port, tls_port, ipad_ip):
        self.port, self.tls_port, self.ipad_ip = port, tls_port, ipad_ip
        self.server = self.bridge = None
        self.job = make_job()
        self.lock = threading.Lock()
        self.stopping = False
        self.env = dict(os.environ, IPAD_BRIDGE_DATA=str(DATA), PYTHONIOENCODING="utf-8")
        if FFMPEG.exists():
            self.env["FFMPEG"] = str(FFMPEG)

    def _spawn(self, args, out, err=None):
        f_out = open(DATA / out, "w", encoding="utf-8", errors="replace")
        f_err = open(DATA / err, "w", encoding="utf-8", errors="replace") if err else subprocess.STDOUT
        p = subprocess.Popen([str(PYTHON), "-u", *args], cwd=ROOT, env=self.env, stdout=f_out, stderr=f_err,
                             stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        f_out.close()
        if f_err is not subprocess.STDOUT:
            f_err.close()
        if self.job:
            ctypes.windll.kernel32.AssignProcessToJobObject(self.job, int(p._handle))
        log.info("lanzado pid %d: %s", p.pid, " ".join(args))
        return p

    def make_certs(self):
        r = subprocess.run([str(PYTHON), str(ROOT / "tools" / "make_certs.py")], cwd=ROOT, env=self.env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        log.info("certificados: %s%s", r.stdout.strip().replace("\n", " | "), r.stderr.strip())

    def start(self):
        with self.lock:
            self.stopping = False
            if self.server is None or self.server.poll() is not None:
                self.make_certs()
                self.server = self._spawn(["server.py", str(self.port), str(self.tls_port)], "server.out.log")
            if self.bridge is None or self.bridge.poll() is not None:
                args = ["usb_bridge.py", "auto", f"ws://localhost:{self.port}/ws"]
                if self.ipad_ip:
                    args.append(self.ipad_ip)
                self.bridge = self._spawn(args, "bridge.log", "bridge.err")

    def stop(self):
        with self.lock:
            self.stopping = True
            for name in ("bridge", "server"):
                p = getattr(self, name)
                if p is not None and p.poll() is None:
                    log.info("cerrando %s (pid %d)", name, p.pid)
                    p.kill()           # ffmpeg es hijo del servidor y está en el mismo job; sin SIGTERM en Windows
                    try:
                        p.wait(5)
                    except subprocess.TimeoutExpired:
                        pass
                setattr(self, name, None)

    def restart(self):
        self.stop()
        time.sleep(0.5)
        self.start()

    def restart_bridge(self):
        with self.lock:
            if self.bridge is not None and self.bridge.poll() is None:
                self.bridge.kill()
                self.bridge.wait(5)
            self.bridge = None
        self.start()

    def check(self):
        """Vigilancia cada 2 s: relanza lo que se haya caído (p. ej. el servidor por un error de ffmpeg)."""
        if self.stopping:
            return None
        dead = [n for n in ("server", "bridge") if getattr(self, n) is not None and getattr(self, n).poll() is not None]
        for n in dead:
            log.warning("%s terminó con código %s; relanzo en 3 s", n, getattr(self, n).returncode)
        if dead:
            time.sleep(3)
            self.start()
        return dead


def usbmux_available():
    try:
        with socket.create_connection(("127.0.0.1", USBMUX_PORT), timeout=0.3):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- estado por WebSocket (lo mismo que pc.html)

class Status:
    """Cliente de estado: hello role=status y luego un mensaje `status` cada 2 s. `info` trae las URLs."""

    def __init__(self, port, on_change):
        self.port, self.on_change = port, on_change
        self.connected = False
        self.last = {}
        self.info = {}
        self.stop = threading.Event()
        threading.Thread(target=lambda: asyncio.run(self._run()), name="status", daemon=True).start()

    async def _run(self):
        import aiohttp
        while not self.stop.is_set():
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"ws://127.0.0.1:{self.port}/ws", heartbeat=10) as ws:
                        await ws.send_json({"type": "hello", "role": "status"})
                        self.connected = True
                        self.on_change()
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            m = json.loads(msg.data)
                            if m.get("type") == "status":
                                self.last = m
                                self.on_change()
                            elif m.get("type") == "info":
                                self.info = m
            except Exception as e:                       # servidor arrancando, reiniciando o caído: reintento
                log.debug("estado: %s", e)
            if self.connected:
                self.connected, self.last = False, {}
                self.on_change()
            await asyncio.sleep(2)


# ---------------------------------------------------------------- bandeja

class Tray:
    def __init__(self, bridge):
        self.bridge = bridge
        self.state = "down"
        self.status = Status(bridge.port, self.refresh)
        self.usbmux = usbmux_available()
        self.icon = pystray.Icon("iPad Bridge", icon_image("down"), "iPad Bridge: arrancando", menu=self.menu())
        self._last_notified = None
        threading.Thread(target=self.watch, name="watch", daemon=True).start()

    # -- estado derivado
    def compute_state(self):
        if not self.status.connected:
            return "down"
        tr = self.status.last.get("transports", [])
        return "usb" if "usb" in tr else "net" if tr else "off"

    def state_text(self):
        s = self.status.last
        return {"down": "servidor arrancando / sin respuesta", "off": "sin iPad conectado",
                "usb": "iPad conectado por USB", "net": "iPad conectado por red"}[self.state] + \
            (f" ({s['viewers']} visores)" if s.get("viewers", 0) > 1 else "")

    def capture_text(self):
        s = self.status.last
        if not s:
            return "Captura: -"
        if not s.get("capturing"):
            t = s.get("target", {})
            return f"Captura detenida · monitor {t.get('name', '?')} {t.get('width', '?')}x{t.get('height', '?')} @ {t.get('hz', '?')} Hz"
        q = s.get("quality", {})
        return f"Captura: {s.get('fps', 0)} fps · {s.get('mbps', 0)} Mbps · {q.get('width', '?')}x{q.get('height', '?')} · nivel {q.get('level', '?')}"

    def viewer_items(self):
        s = self.status.last
        stats = s.get("viewer_stats") or []
        if not s.get("viewers"):
            return [pystray.MenuItem("ninguno", None, enabled=False)]
        items = []
        for v in stats:
            via = "USB" if v.get("transport") == "usb" else f"red {v.get('remote', '?')}"
            items.append(pystray.MenuItem(f"{via}: {v.get('fps', '?')} fps · {v.get('mbps', '?')} Mbps · e2e {v.get('e2e50', '?')} ms · RTT {v.get('rtt', '?')} ms",
                                          None, enabled=False))
        for _ in range(s["viewers"] - len(stats)):
            items.append(pystray.MenuItem("visor sin estadísticas todavía", None, enabled=False))
        return items

    def ipad_url(self):
        return self.status.info.get("ipad_url") or f"https://{local_ip()}/ipad.html"

    # -- menú
    def menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda i: f"iPad Bridge: {self.state_text()}", None, enabled=False),
            pystray.MenuItem(lambda i: self.capture_text(), None, enabled=False),
            pystray.MenuItem(lambda i: f"Visores ({self.status.last.get('viewers', 0)})", pystray.Menu(lambda: self.viewer_items())),
            pystray.MenuItem("Falta el servicio USB de Apple (instalá \"Dispositivos Apple\")", self.open_apple_devices,
                             visible=lambda i: not self.usbmux),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir panel de estado", self.open_panel, default=True),
            pystray.MenuItem(lambda i: f"Dirección para el iPad: {self.ipad_url()}", self.open_setup),
            pystray.MenuItem("Abrir carpeta de logs", self.open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda i: f"IP de respaldo del iPad: {self.bridge.ipad_ip or 'ninguna (solo USB)'}…", self.edit_ip),
            pystray.MenuItem("Ubicar el monitor virtual (izquierda, 120 Hz, 225 %)", self.place_vdd),
            pystray.MenuItem("Iniciar con Windows", self.toggle_startup, checked=lambda i: startup_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Reiniciar servidor", self.restart),
            pystray.MenuItem("Salir", self.quit),
        )

    def refresh(self):
        new = self.compute_state()
        if new != self.state:
            log.info("estado: %s -> %s", self.state, new)
            self.state = new
            self.icon.icon = icon_image(new)
            if new in ("usb", "net") and self._last_notified != new:
                self.notify("iPad conectado por " + ("USB" if new == "usb" else "red"))
            self._last_notified = new
        s = self.status.last
        self.icon.title = ("iPad Bridge: " + self.state_text() + (f" · {s['fps']} fps · {s['mbps']} Mbps" if s.get("capturing") else ""))[:127]
        try:
            self.icon.update_menu()
        except Exception:        # el icono todavía no está en la bandeja
            pass

    def notify(self, text):
        try:
            self.icon.notify(text, "iPad Bridge")
        except Exception:
            pass

    def watch(self):
        while True:
            time.sleep(2)
            try:
                dead = self.bridge.check()
                if dead:
                    self.notify("Se cayó " + " y ".join("el servidor" if d == "server" else "el puente" for d in dead) + "; lo relanzo")
                if not self.usbmux:
                    self.usbmux = usbmux_available()
            except Exception:
                log.exception("vigilancia")

    # -- acciones
    def open_panel(self, *_):
        webbrowser.open(f"http://localhost{'' if self.bridge.port == 80 else ':%d' % self.bridge.port}/pc.html")

    def open_setup(self, *_):
        webbrowser.open(self.status.info.get("setup_url") or f"http://{local_ip()}/")

    def open_logs(self, *_):
        os.startfile(DATA)

    def open_apple_devices(self, *_):
        webbrowser.open("ms-windows-store://pdp/?productid=9NP83LWLPZ9K")

    def edit_ip(self, *_):
        r = input_box("iPad Bridge", "IP del iPad para usar la red cuando no está por cable (vacío = solo USB).\n"
                      "La ves en el iPad en Ajustes > Wi-Fi (i) o en la app iPadBridge.", self.bridge.ipad_ip or "")
        if r is None:
            return
        self.bridge.ipad_ip = r.strip()
        save_config(dict(load_config(), ipad_ip=self.bridge.ipad_ip))
        self.bridge.restart_bridge()
        self.refresh()

    def place_vdd(self, *_):
        r = subprocess.run([str(PYTHON), str(ROOT / "tools" / "place_vdd.py"), "left", "--hz=120", "--scale=225"], cwd=ROOT,
                           env=self.bridge.env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
        out = (r.stdout + r.stderr).strip()
        log.info("place_vdd: %s", out.replace("\n", " | "))
        message_box(out[-1500:] or "listo", "Monitor virtual", 0x40 if r.returncode == 0 else 0x30)

    def toggle_startup(self, *_):
        set_startup(not startup_enabled())
        self.refresh()

    def restart(self, *_):
        threading.Thread(target=self.bridge.restart, daemon=True).start()

    def quit(self, *_):
        self.icon.visible = False
        self.bridge.stop()
        self.icon.stop()

    def run(self):
        self.icon.run(setup=lambda icon: (icon.__setattr__("visible", True), self.refresh()))


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(DATA / "tray.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[h], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not single_instance():
        message_box("iPad Bridge ya está en la bandeja.")
        return
    import argparse
    ap = argparse.ArgumentParser(description="iPad Bridge en la bandeja")
    ap.add_argument("ipad_ip", nargs="?", default=None, help="IP del iPad de respaldo (si no, la guardada en config.json)")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--tls-port", type=int, default=443)
    a = ap.parse_args()
    port, tls_port = a.port, a.tls_port
    cfg = load_config()
    ipad_ip = a.ipad_ip if a.ipad_ip is not None else cfg.get("ipad_ip", "")
    log.info("iPad Bridge: %s, datos en %s, python %s, puertos %d/%d, IP de respaldo %r", "instalado" if INSTALLED else "desarrollo",
             DATA, PYTHON, port, tls_port, ipad_ip)
    bridge = Bridge(port, tls_port, ipad_ip)
    bridge.start()
    try:
        Tray(bridge).run()
    finally:
        bridge.stop()
        log.info("bandeja cerrada")


if __name__ == "__main__":
    main()
