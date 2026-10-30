"""Inyección de input en Windows (ctypes, sin dependencias):
- Mouse: SendInput, para los dedos.
- Pen: lápiz virtual con CreateSyntheticPointerDevice(PT_PEN) + InjectSyntheticPointerInput (Windows 10 1809+).
  Windows lo entrega a las apps como WM_POINTER de lápiz (Windows Ink) con presión, inclinación, botón lateral y
  goma, y además genera el mouse equivalente para las apps que no entienden lápiz. Photoshop lo lee en su modo
  Windows Ink (el de fábrica) igual que un Wacom."""
import ctypes
import logging
import math
import os
import re
import time
from ctypes import wintypes

log = logging.getLogger("winput")

user32 = ctypes.windll.user32
try:
    # Per-monitor DPI aware v2: EnumDisplayMonitors y SendInput trabajan en píxeles físicos.
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    user32.SetProcessDPIAware()

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "esc": 0x1B, "tab": 0x09, "space": 0x20, "enter": 0x0D,
      "backspace": 0x08, "delete": 0x2E, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
      "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B, "[": 0xDB, "]": 0xDD,
      # Navegación y edición
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
      "insert": 0x2D, "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "pause": 0x13, "printscreen": 0x2C,
      "apps": 0x5D, "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F, "f17": 0x80, "f18": 0x81, "f19": 0x82,
      "f20": 0x83, "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
      # Teclado numérico
      "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64, "num5": 0x65, "num6": 0x66, "num7": 0x67,
      "num8": 0x68, "num9": 0x69, "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
      # Multimedia
      "volumeup": 0xAF, "volumedown": 0xAE, "mute": 0xAD, "playpause": 0xB3}
# Sinónimos (nombres de KeyboardEvent.key de Safari y abreviaturas habituales)
VK_ALIAS = {"control": "ctrl", "meta": "win", "cmd": "win", "command": "win", "option": "alt", "escape": "esc",
            "return": "enter", "del": "delete", "bksp": "backspace", "ins": "insert", "pgup": "pageup", "pgdn": "pagedown",
            "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down", "spacebar": "space",
            "esp": "space", "supr": "delete", "inicio": "home", "fin": "end", "contextmenu": "apps", "prtsc": "printscreen"}
# Teclas que Windows marca como "extendidas" (scan code E0): sin la bandera algunas apps las confunden con el numérico.
VK_EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E, 0x90, 0x2C, 0x5B, 0x5D, 0x6F, 0xAF, 0xAE, 0xAD, 0xB3}


def _vk_mods(name):
    """(código de tecla virtual, modificadores que necesita) para un nombre de tecla. Un carácter suelto se resuelve
    con la distribución del teclado activa: '{' es shift+'[' en un teclado US y AltGr+' en uno español."""
    name = name.strip().lower()
    name = VK_ALIAS.get(name, name)
    if name in VK:
        return VK[name], []
    if len(name) == 1:
        r = user32.VkKeyScanW(ord(name))
        if r != -1 and (r & 0xFF) != 0xFF:
            st = (r >> 8) & 0xFF
            mods = [VK[m] for bit, m in ((1, "shift"), (2, "ctrl"), (4, "alt")) if st & bit]
            return r & 0xFF, mods
    raise ValueError(f"tecla desconocida: {name}")


def _vk(name):
    return _vk_mods(name)[0]


def _key(vk, up=False):
    inp = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in VK_EXTENDED else 0)
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def type_text(text):
    """Escribe texto tal cual (teclado en pantalla del iPad): cada carácter va como KEYEVENTF_UNICODE, así no
    depende de la distribución del teclado ni del estado de shift/bloq mayús."""
    for ch in str(text):
        raw = ch.encode("utf-16-le")   # un emoji son dos unidades (par sustituto): van las dos
        units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
        for u in units:
            for up in (False, True):
                inp = INPUT(type=INPUT_KEYBOARD)
                inp.ki = KEYBDINPUT(0, u, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, None)
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap_keys(spec):
    """Pulsa un atajo en la ventana activa: 'e', 'ctrl+z', 'ctrl+shift+z', 'ctrl+num+'. Modificadores: ctrl, shift, alt,
    win. Un carácter que en el teclado activo pide shift ('{', '+') lo agrega solo. Si la barra de teclas tiene un
    modificador mantenido (hold_key) se suma, como en un teclado real."""
    # Separador '+'; "num+" es un nombre y un '+' final suelto ("ctrl++", "+") es la tecla más.
    parts = re.findall(r"num[+*\-./]|[^+]+|\+(?=$)", spec.strip())
    keys, extra = [], []
    for k in parts:
        vk, mods = _vk_mods(k)
        keys.append(vk)
        extra += [m for m in mods if m not in keys and m not in extra and m not in _held]
    keys = extra + keys
    for k in keys:
        _key(k)
    for k in reversed(keys):
        _key(k, up=True)


_held = set()   # teclas mantenidas por la barra lateral del iPad (vk)


def hold_key(name, down=True):
    """Mantiene una tecla presionada (down=True) hasta su hold_key(name, False): shift = línea recta,
    alt = cuentagotas, space = mano, ctrl, mientras se sigue dibujando con el Pencil."""
    vk = _vk(name)
    if down and vk not in _held:
        _held.add(vk)
        _key(vk)
    elif not down and vk in _held:
        _held.discard(vk)
        _key(vk, up=True)


def release_keys():
    """Suelta todo lo mantenido con hold_key (visor desconectado, barra oculta)."""
    for vk in list(_held):
        _key(vk, up=True)
    _held.clear()


def held_keys():
    return set(_held)


def monitors():
    """Lista de rects (left, top, right, bottom) de cada monitor, el primario primero."""
    rects = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                         ctypes.POINTER(wintypes.RECT), ctypes.c_double)

    def cb(hmon, hdc, lprc, lparam):
        r = lprc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1

    user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(cb), 0)
    rects.sort(key=lambda r: (r[0] != 0 or r[1] != 0, r[0], r[1]))
    return rects


class DEVMODE(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long), ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", ctypes.c_wchar * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", wintypes.DWORD), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


def target_display():
    """El monitor que va al iPad: el 'Virtual Display Driver' si está activo, si no el principal.
    Devuelve dict(name, rect=(l, t, r, b), virtual=bool) en píxeles físicos."""
    i, primary = 0, None
    while True:
        d = DISPLAY_DEVICE(); d.cb = ctypes.sizeof(d)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        i += 1
        if not d.StateFlags & 1:
            continue
        dm = DEVMODE(); dm.dmSize = ctypes.sizeof(dm)
        if not user32.EnumDisplaySettingsW(d.DeviceName, -1, ctypes.byref(dm)):
            continue
        rect = (dm.dmPositionX, dm.dmPositionY, dm.dmPositionX + dm.dmPelsWidth, dm.dmPositionY + dm.dmPelsHeight)
        info = {"name": d.DeviceString, "rect": rect, "virtual": "Virtual Display" in d.DeviceString,
                "hz": int(dm.dmDisplayFrequency) or 60}
        if info["virtual"]:
            return info
        if d.StateFlags & 4 or primary is None:
            primary = info
    return primary


def foreground_app():
    """Ventana activa de Windows: (nombre del ejecutable, título). Para la barra de atajos por aplicación del iPad.
    Devuelve ("", "") si no hay ventana o no se puede consultar (ventanas del sistema con más privilegios)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    if pid.value:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    exe = os.path.basename(buf.value)
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
    n = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, title, n + 1)
    return exe, title.value


class Mouse:
    """Mapea coordenadas 0..1 del iPad al monitor objetivo (virtual si existe) e inyecta eventos."""

    def __init__(self):
        self.buttons = set()
        self._stamp = 0.0
        self.refresh(force=True)

    def refresh(self, force=False):
        import time
        now = time.monotonic()
        if not force and now - self._stamp < 2.0:
            return
        self._stamp = now
        self.target = target_display() or {"name": "?", "rect": (0, 0, 1, 1), "virtual": False}
        self.rect = self.target["rect"]
        self.vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        self.vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        self.vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1
        self.vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1

    def pixel(self, nx, ny):
        """Coordenadas 0..1 del iPad -> píxel físico del escritorio (dentro del monitor objetivo)."""
        self.refresh()
        l, t, r, b = self.rect
        return int(l + nx * (r - l)), int(t + ny * (b - t))

    def move(self, nx, ny):
        self.refresh()
        l, t, r, b = self.rect
        px = l + nx * (r - l)
        py = t + ny * (b - t)
        ax = int((px - self.vx) * 65535 / self.vw)
        ay = int((py - self.vy) * 65535 / self.vh)
        _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)

    def down(self, btn=0):
        self.buttons.add(btn)
        _send({0: MOUSEEVENTF_LEFTDOWN, 1: MOUSEEVENTF_MIDDLEDOWN, 2: MOUSEEVENTF_RIGHTDOWN}[btn])

    def up(self, btn=0):
        self.buttons.discard(btn)
        _send({0: MOUSEEVENTF_LEFTUP, 1: MOUSEEVENTF_MIDDLEUP, 2: MOUSEEVENTF_RIGHTUP}[btn])

    def release_all(self):
        for b in list(self.buttons):
            self.up(b)

    def scroll(self, dy=0, dx=0):
        if dy:
            _send(MOUSEEVENTF_WHEEL, data=int(dy) & 0xFFFFFFFF)
        if dx:
            _send(MOUSEEVENTF_HWHEEL, data=int(dx) & 0xFFFFFFFF)


# ---------------------------------------------------------------- lápiz virtual (pointer injection)

PT_PEN = 3
POINTER_FEEDBACK_NONE = 3          # sin ondas ni animaciones de Windows al tocar
PF_NEW, PF_INRANGE, PF_INCONTACT = 0x1, 0x2, 0x4
PF_FIRSTBUTTON, PF_SECONDBUTTON = 0x10, 0x20
PF_PRIMARY, PF_CONFIDENCE = 0x2000, 0x4000
PF_DOWN, PF_UPDATE, PF_UP = 0x10000, 0x20000, 0x40000
PEN_FLAG_BARREL, PEN_FLAG_INVERTED, PEN_FLAG_ERASER = 1, 2, 4
PEN_MASK_PRESSURE, PEN_MASK_ROTATION, PEN_MASK_TILT_X, PEN_MASK_TILT_Y = 1, 2, 4, 8


class POINTER_INFO(ctypes.Structure):
    _fields_ = [("pointerType", ctypes.c_uint32), ("pointerId", ctypes.c_uint32), ("frameId", ctypes.c_uint32),
                ("pointerFlags", ctypes.c_uint32), ("sourceDevice", ctypes.c_void_p), ("hwndTarget", ctypes.c_void_p),
                ("ptPixelLocation", wintypes.POINT), ("ptHimetricLocation", wintypes.POINT),
                ("ptPixelLocationRaw", wintypes.POINT), ("ptHimetricLocationRaw", wintypes.POINT),
                ("dwTime", wintypes.DWORD), ("historyCount", ctypes.c_uint32), ("InputData", ctypes.c_int32),
                ("dwKeyStates", wintypes.DWORD), ("PerformanceCount", ctypes.c_uint64), ("ButtonChangeType", ctypes.c_int)]


class POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("penFlags", ctypes.c_uint32), ("penMask", ctypes.c_uint32),
                ("pressure", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("tiltX", ctypes.c_int32), ("tiltY", ctypes.c_int32)]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("touchFlags", ctypes.c_uint32), ("touchMask", ctypes.c_uint32),
                ("rcContact", wintypes.RECT), ("rcContactRaw", wintypes.RECT), ("orientation", ctypes.c_uint32),
                ("pressure", ctypes.c_uint32)]


class POINTER_TYPE_INFO(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("touchInfo", POINTER_TOUCH_INFO), ("penInfo", POINTER_PEN_INFO)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _U)]


def pen_supported():
    return all(hasattr(user32, n) for n in ("CreateSyntheticPointerDevice", "InjectSyntheticPointerInput"))


def tilt_from_angles(altitude, azimuth):
    """Altitud/azimut de UIKit (radianes; altitud pi/2 = vertical, azimut 0 = +x, crece en sentido horario) ->
    (tiltX, tiltY) en grados como los define Windows/W3C: X positivo inclinado a la derecha, Y positivo hacia el usuario."""
    if altitude is None or azimuth is None:
        return 0, 0
    alt = max(0.01, min(math.pi / 2, float(altitude)))
    k = 1.0 / math.tan(alt)
    tx = math.degrees(math.atan(math.cos(azimuth) * k))
    ty = math.degrees(math.atan(math.sin(azimuth) * k))
    return int(round(tx)), int(round(ty))


class OneEuro:
    """Filtro 1€ (Casiez 2012): paso bajo cuya frecuencia de corte sube con la velocidad. Quieto suaviza mucho
    (sin temblor), rápido casi no filtra (sin retraso). `mincutoff` en Hz, `beta` cuánto abre con la velocidad."""

    def __init__(self, mincutoff=1.0, beta=0.0, dcutoff=1.0):
        self.mincutoff, self.beta, self.dcutoff = mincutoff, beta, dcutoff
        self.reset()

    def reset(self):
        self.x = self.dx = None
        self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.x is None or self.t is None or t <= self.t:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = t - self.t
        self.t = t
        dx = (x - self.x) / dt
        a_d = self._alpha(self.dcutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.mincutoff + self.beta * abs(self.dx)
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


class Pen:
    """Lápiz virtual mapeado al mismo monitor que Mouse. Estado: fuera de alcance -> en alcance (hover) -> en contacto.
    Cada método inyecta un evento coherente con el estado anterior (Windows rechaza secuencias inválidas)."""

    def __init__(self, mouse):
        self.mouse = mouse
        self.dev = None
        self.inrange = False
        self.contact = False
        self.barrel = False
        self.last = 0.0           # monotonic del último evento (para salir de alcance al quedar quieto)
        self.pressure = 0.0
        # Curva de presión: salida = entrada ** gamma. <1 responde más con poca fuerza (Pencil pide más fuerza que un
        # Wacom para la misma presión), >1 más duro. Como la curva del driver de Wacom, pero global.
        self.gamma = float(os.environ.get("PEN_GAMMA", "0.8"))
        self.min_pressure = float(os.environ.get("PEN_MIN", "0.02"))   # umbral de activación en contacto
        # Suavizado 0..1 (0 = apagado) con filtro 1€ sobre posición y presión; el iPad lo cambia con "pencfg".
        self.smooth = 0.0
        self._fx, self._fy, self._fp = OneEuro(), OneEuro(), OneEuro()
        self.configure(smooth=float(os.environ.get("PEN_SMOOTH", "0")))
        self.raw_pressure = 0.0   # última presión cruda del iPad (para el HUD/estado)
        self.available = pen_supported()
        if self.available:
            user32.CreateSyntheticPointerDevice.restype = ctypes.c_void_p
            user32.CreateSyntheticPointerDevice.argtypes = [ctypes.c_uint32, ctypes.c_ulong, ctypes.c_int]
            user32.InjectSyntheticPointerInput.restype = wintypes.BOOL
            user32.InjectSyntheticPointerInput.argtypes = [ctypes.c_void_p, ctypes.POINTER(POINTER_TYPE_INFO), ctypes.c_uint32]
            user32.DestroySyntheticPointerDevice.argtypes = [ctypes.c_void_p]
            self._open()

    def _open(self):
        self.dev = user32.CreateSyntheticPointerDevice(PT_PEN, 1, POINTER_FEEDBACK_NONE)
        if not self.dev:
            err = ctypes.GetLastError()
            log.error("no pude crear el lápiz virtual (error %d); el Pencil queda como mouse", err)
            self.available = False
        self.inrange = self.contact = False

    def close(self):
        if self.dev:
            user32.DestroySyntheticPointerDevice(self.dev)
            self.dev = None

    def curve(self, p):
        p = max(0.0, min(1.0, float(p or 0)))
        return p ** self.gamma if p > 0 else 0.0

    def configure(self, gamma=None, min_pressure=None, smooth=None):
        """Curva, umbral y suavizado en caliente (mensaje "pencfg" del iPad). Valores fuera de rango se recortan.
        smooth 0 = sin filtro; 1 = corte de 0.6 Hz en reposo (muy suave, se nota el retraso en trazos lentos)."""
        if gamma is not None:
            self.gamma = max(0.2, min(3.0, float(gamma)))
        if min_pressure is not None:
            self.min_pressure = max(0.0, min(0.5, float(min_pressure)))
        if smooth is not None:
            self.smooth = max(0.0, min(1.0, float(smooth)))
            # Frecuencia de corte en reposo: 12 Hz (apenas quita temblor) -> 0.6 Hz. beta abre el filtro con la
            # velocidad (en pantallas/s): a 0.5 pantallas/s suma ~4 Hz, así los trazos rápidos no se retrasan.
            fc = 12.0 * (1.0 - self.smooth) ** 2 + 0.6
            for f in (self._fx, self._fy):
                f.mincutoff, f.beta = fc, 8.0
            self._fp.mincutoff, self._fp.beta = fc * 1.5, 2.0
        self._reset_filters()
        log.info("lápiz: gamma %.2f, mínimo %.3f, suavizado %.2f", self.gamma, self.min_pressure, self.smooth)

    def _reset_filters(self):
        for f in (self._fx, self._fy, self._fp):
            f.reset()

    def _filter(self, nx, ny, p, t):
        """Posición y presión filtradas (si smooth > 0). t: segundos monotónicos del punto."""
        self.raw_pressure = float(p or 0.0)
        if self.smooth <= 0:
            return nx, ny, p
        t = time.monotonic() if t is None else t
        fx, fy = self._fx(float(nx), t), self._fy(float(ny), t)
        fp = self._fp(float(p), t) if p is not None else None
        return fx, fy, fp

    def _inject(self, flags, nx, ny, p=0.0, tx=0, ty=0):
        # Dentro del monitor: un punto fuera del escritorio virtual hace fallar la inyección con ERROR_INVALID_PARAMETER.
        nx, ny = min(1.0, max(0.0, float(nx))), min(1.0, max(0.0, float(ny)))
        px, py = self.mouse.pixel(nx, ny)
        # InjectSyntheticPointerInput toma ptPixelLocation relativa a la esquina superior izquierda del escritorio
        # virtual (documentado), no en coordenadas de pantalla como SendInput. Con el monitor virtual a la izquierda
        # del principal el origen es negativo (p. ej. -2732, 0): sin restar, todo el trazo cae fuera de pantalla y
        # Windows lo descarta (medido: el lápiz no llegaba al iPad, un trazo pedido en x=1000 caía en x=-1732).
        px, py = px - self.mouse.vx, py - self.mouse.vy
        info = POINTER_TYPE_INFO()
        info.type = PT_PEN
        pi = info.penInfo.pointerInfo
        pi.pointerType = PT_PEN
        pi.pointerId = 0
        pi.pointerFlags = flags
        pi.ptPixelLocation.x = pi.ptPixelLocationRaw.x = px
        pi.ptPixelLocation.y = pi.ptPixelLocationRaw.y = py
        pen = info.penInfo
        # Solo BARREL llega a las apps. PEN_FLAG_INVERTED/ERASER no se entregan en lápices sintéticos (medido: la app
        # recibe penFlags 0 y ERASER se toma como contacto), así que la goma del Pencil se resuelve con teclas (server).
        pen.penFlags = PEN_FLAG_BARREL if self.barrel else 0
        pen.penMask = PEN_MASK_PRESSURE | PEN_MASK_TILT_X | PEN_MASK_TILT_Y
        pen.pressure = int(round(1024 * max(0.0, min(1.0, p))))
        pen.tiltX = max(-90, min(90, int(tx)))
        pen.tiltY = max(-90, min(90, int(ty)))
        self.last = time.monotonic()
        self._last_pos = (nx, ny)
        if not user32.InjectSyntheticPointerInput(self.dev, ctypes.byref(info), 1):
            err = ctypes.GetLastError()
            log.warning("InjectSyntheticPointerInput falló (error %d, flags 0x%x, px=%d py=%d p=%.2f tilt=%d,%d inrange=%s contact=%s); reinicio el lápiz",
                        err, flags, px, py, p, int(tx), int(ty), self.inrange, self.contact)
            # Estado desincronizado (p. ej. UP sin DOWN): recrear el dispositivo deja todo fuera de alcance.
            self.close()
            self._open()
            return False
        return True

    def _buttons(self):
        f = PF_FIRSTBUTTON if self.contact else 0
        if self.barrel:
            f |= PF_SECONDBUTTON
        return f

    def hover(self, nx, ny, tx=0, ty=0):
        """Lápiz cerca de la pantalla sin tocar: mueve el cursor del lápiz (Photoshop muestra el pincel)."""
        if self.contact:
            return self.move(nx, ny, self.pressure, tx, ty)
        flags = PF_INRANGE | PF_UPDATE | PF_PRIMARY | self._buttons()
        self.inrange = True
        self._inject(flags, nx, ny, 0.0, tx, ty)

    def down(self, nx, ny, p=0.0, tx=0, ty=0, t=None):
        if self.contact:
            return self.move(nx, ny, p, tx, ty, t)
        self._reset_filters()                       # cada trazo arranca en el punto real, sin arrastre del anterior
        nx, ny, p = self._filter(nx, ny, p, t)
        if not self.inrange:
            # Sin hover (iPad sin detección de Pencil en el aire): entrar en alcance justo antes de tocar.
            self._inject(PF_INRANGE | PF_UPDATE | PF_PRIMARY, nx, ny, 0.0, tx, ty)
            self.inrange = True
        self.contact = True
        self.pressure = max(self.min_pressure, self.curve(p))
        flags = PF_INRANGE | PF_INCONTACT | PF_DOWN | PF_PRIMARY | self._buttons()
        if not self._inject(flags, nx, ny, self.pressure, tx, ty):
            self.contact = False

    def move(self, nx, ny, p=None, tx=0, ty=0, t=None):
        if not self.contact:
            return self.hover(nx, ny, tx, ty)
        nx, ny, p = self._filter(nx, ny, p, t)
        if p is not None:
            self.pressure = max(self.min_pressure, self.curve(p))
        flags = PF_INRANGE | PF_INCONTACT | PF_UPDATE | PF_PRIMARY | self._buttons()
        self._inject(flags, nx, ny, self.pressure, tx, ty)

    def up(self, nx, ny, tx=0, ty=0):
        if not self.contact:
            return
        if self.smooth > 0 and self._fx.x is not None:
            nx, ny = self._fx.x, self._fy.x        # levantar donde quedó el trazo filtrado, sin salto final
        self.contact = False
        self.pressure = self.raw_pressure = 0.0
        flags = PF_INRANGE | PF_UP | PF_PRIMARY | self._buttons()
        self._inject(flags, nx, ny, 0.0, tx, ty)

    def leave(self):
        """Lápiz lejos de la pantalla: Windows vuelve al cursor normal y el mouse de los dedos retoma el control."""
        if self.contact:
            self.up(*self._last_pos)
        if not self.inrange:
            return
        self.inrange = False
        self._inject(PF_UPDATE | PF_PRIMARY, *self._last_pos)

    _last_pos = (0.5, 0.5)

    def leave_if_idle(self, stamp):
        """Para iPads sin hover: tras soltar, si no llegó nada más, salir de alcance."""
        if self.last == stamp and self.inrange and not self.contact:
            self.leave()

    def set_barrel(self, on):
        self.barrel = bool(on)

    def release_all(self):
        self.barrel = False
        self.leave()


if __name__ == "__main__":
    print("monitores:", monitors())
    print("objetivo:", target_display())
    print("lápiz virtual:", "disponible" if pen_supported() else "NO disponible (Windows 10 1809+)")
    print("app activa:", foreground_app())
