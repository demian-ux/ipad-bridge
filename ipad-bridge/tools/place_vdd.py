"""Ubica el monitor virtual: python tools/place_vdd.py left|right [desplazamiento_y] [--hz=120] [--scale=225]

- Si Windows tiene el monitor virtual desconectado del escritorio (pasa tras cambios de pantallas o de driver; el
  servidor arranca en modo espejo), lo vuelve a conectar a 2732x2048.
- Lo ubica a la izquierda o derecha del principal, centrado verticalmente, y fija el refresco (--hz).
- --scale fija la escala de Windows (DPI) de ese monitor: 225 deja la interfaz de Photoshop cómoda en el iPad de 13".
  Usa DisplayConfigSetDeviceInfo con el tipo -4 (no documentado, estable desde Windows 10; es lo que usan SetDPI y
  similares). Valores válidos: 100 125 150 175 200 225 250 300 350 400 450 500, dentro del rango que Windows permite
  para ese monitor.
"""
import ctypes, sys
from ctypes import wintypes
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import winput  # activa DPI awareness: todo en píxeles físicos

user32 = ctypes.windll.user32
CDS_UPDATEREGISTRY, CDS_NORESET = 0x1, 0x10000000
DM_POSITION, DM_BITSPERPEL, DM_PELSWIDTH, DM_PELSHEIGHT, DM_DISPLAYFREQUENCY = 0x20, 0x40000, 0x80000, 0x100000, 0x400000
VDD_W, VDD_H = 2732, 2048          # iPad Pro 12.9"
DPI_VALS = [100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500]


class DEVMODE(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD), ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long), ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128), ("StateFlags", wintypes.DWORD), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


def all_displays():
    """[(DISPLAY_DEVICE, DEVMODE actual o None si está inactivo)] de todos los adaptadores de pantalla."""
    out, i = [], 0
    while True:
        d = DISPLAY_DEVICE(); d.cb = ctypes.sizeof(d)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        dm = None
        if d.StateFlags & 1:
            dm = DEVMODE(); dm.dmSize = ctypes.sizeof(dm)
            user32.EnumDisplaySettingsW(d.DeviceName, -1, ctypes.byref(dm))
        out.append((d, dm))
        i += 1
    return out


def active_displays():
    return [(d, dm) for d, dm in all_displays() if dm is not None]


def modes(device_name):
    out, j = set(), 0
    while True:
        dm = DEVMODE(); dm.dmSize = ctypes.sizeof(dm)
        if not user32.EnumDisplaySettingsW(device_name, j, ctypes.byref(dm)):
            break
        out.add((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency)); j += 1
    return out


def apply(dev, dm):
    r1 = user32.ChangeDisplaySettingsExW(dev.DeviceName, ctypes.byref(dm), None, CDS_UPDATEREGISTRY | CDS_NORESET, None)
    r2 = user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return r1, r2


def attach(dev, primary, side, dy, hz):
    """Conecta al escritorio un monitor virtual que Windows tiene desconectado."""
    ms = modes(dev.DeviceName)
    hz = hz if hz and (VDD_W, VDD_H, hz) in ms else (120 if (VDD_W, VDD_H, 120) in ms else 60)
    dm = DEVMODE(); dm.dmSize = ctypes.sizeof(dm)
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel = VDD_W, VDD_H, hz, 32
    dm.dmPositionX = -VDD_W if side == "left" else int(primary.dmPelsWidth)
    dm.dmPositionY = dy if dy is not None else int((int(primary.dmPelsHeight) - VDD_H) // 2)
    dm.dmFields = DM_POSITION | DM_BITSPERPEL | DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
    r1, r2 = apply(dev, dm)
    print(f"monitor virtual estaba desconectado: conectado {VDD_W}x{VDD_H}@{hz} en ({dm.dmPositionX},{dm.dmPositionY}) resultados {r1},{r2} (0 = ok)")
    return r1 == 0 and r2 == 0


# ---- Escala DPI por monitor (DisplayConfig; tipos -3 leer y -4 fijar, no documentados) ----

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", wintypes.UINT), ("modeInfoIdx", wintypes.UINT), ("statusFlags", wintypes.UINT)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", wintypes.UINT), ("modeInfoIdx", wintypes.UINT), ("outputTechnology", wintypes.UINT),
                ("rotation", wintypes.UINT), ("scaling", wintypes.UINT), ("refreshRate", wintypes.UINT * 2), ("scanLineOrdering", wintypes.UINT),
                ("targetAvailable", wintypes.BOOL), ("statusFlags", wintypes.UINT)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE_INFO), ("targetInfo", PATH_TARGET_INFO), ("flags", wintypes.UINT)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", wintypes.UINT), ("id", wintypes.UINT), ("adapterId", LUID), ("data", ctypes.c_byte * 48)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", wintypes.INT), ("size", wintypes.UINT), ("adapterId", LUID), ("id", wintypes.UINT)]


class TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("flags", wintypes.UINT), ("outputTechnology", wintypes.UINT), ("edidManufactureId", wintypes.USHORT),
                ("edidProductCodeId", wintypes.USHORT), ("connectorInstance", wintypes.UINT), ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
                ("monitorDevicePath", wintypes.WCHAR * 128)]


class DPI_SCALE_GET(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("minScaleRel", wintypes.INT), ("curScaleRel", wintypes.INT), ("maxScaleRel", wintypes.INT)]


class DPI_SCALE_SET(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("scaleRel", wintypes.INT)]


def display_paths():
    n_paths, n_modes = wintypes.UINT(), wintypes.UINT()
    if user32.GetDisplayConfigBufferSizes(2, ctypes.byref(n_paths), ctypes.byref(n_modes)) != 0:   # QDC_ONLY_ACTIVE_PATHS
        return []
    p = (PATH_INFO * n_paths.value)(); m = (MODE_INFO * n_modes.value)()
    if user32.QueryDisplayConfig(2, ctypes.byref(n_paths), p, ctypes.byref(n_modes), m, None) != 0:
        return []
    return list(p)[: n_paths.value]


def path_monitor_name(path):
    t = TARGET_DEVICE_NAME()
    t.header.type, t.header.size = 2, ctypes.sizeof(t)   # DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
    t.header.adapterId, t.header.id = path.targetInfo.adapterId, path.targetInfo.id
    user32.DisplayConfigGetDeviceInfo(ctypes.byref(t))
    return t.monitorFriendlyDeviceName


def dpi_get(path):
    """(actual, recomendada, mínima, máxima) en % para la fuente de esa ruta, o None."""
    g = DPI_SCALE_GET()
    g.header.type, g.header.size = -3, ctypes.sizeof(g)
    g.header.adapterId, g.header.id = path.sourceInfo.adapterId, path.sourceInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(g)) != 0:
        return None
    rec = -g.minScaleRel
    idx = lambda rel: DPI_VALS[min(len(DPI_VALS) - 1, max(0, rec + rel))]
    return idx(g.curScaleRel), DPI_VALS[rec], DPI_VALS[0], idx(g.maxScaleRel)


def dpi_set(path, percent):
    info = dpi_get(path)
    if info is None or percent not in DPI_VALS:
        return False
    cur, rec, lo, hi = info
    if percent == cur:
        return True
    if not (lo <= percent <= hi):
        print(f"escala {percent}% fuera del rango que permite Windows para ese monitor ({lo}..{hi})")
        return False
    s = DPI_SCALE_SET()
    s.header.type, s.header.size = -4, ctypes.sizeof(s)
    s.header.adapterId, s.header.id = path.sourceInfo.adapterId, path.sourceInfo.id
    s.scaleRel = DPI_VALS.index(percent) - DPI_VALS.index(rec)
    return user32.DisplayConfigSetDeviceInfo(ctypes.byref(s)) == 0


def set_vdd_scale(percent):
    for p in display_paths():
        if "VDD" in path_monitor_name(p):
            before = dpi_get(p)
            ok = dpi_set(p, percent)
            after = dpi_get(p)
            print(f"escala del monitor virtual: {before[0] if before else '?'}% -> {after[0] if after else '?'}% ({'ok' if ok else 'falló'})")
            return ok
    print("no encuentro la ruta de pantalla del monitor virtual para fijar la escala")
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    hz = next((int(a[5:]) for a in sys.argv[1:] if a.startswith("--hz=")), None)
    scale = next((int(a[8:]) for a in sys.argv[1:] if a.startswith("--scale=")), None)
    side = args[0] if args else "left"
    dy = int(args[1]) if len(args) > 1 else None
    disps = all_displays()
    primary = next((dm for d, dm in disps if dm is not None and d.StateFlags & 4), None)
    virt = next(((d, dm) for d, dm in disps if "Virtual Display" in d.DeviceString), None)
    if primary is None or virt is None:
        print("no encuentro el monitor principal o el driver del monitor virtual (¿está instalado?)"); return 1
    d, dm = virt
    if dm is None:
        if not attach(d, primary, side, dy, hz):
            return 1
    else:
        pw, ph = primary.dmPelsWidth, primary.dmPelsHeight
        vw, vh = dm.dmPelsWidth, dm.dmPelsHeight
        dm.dmPositionX = -int(vw) if side == "left" else int(pw)
        dm.dmPositionY = dy if dy is not None else int((ph - vh) // 2)  # centrado verticalmente
        dm.dmFields = DM_POSITION
        if hz:
            dm.dmDisplayFrequency = hz
            dm.dmFields |= DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
        r1, r2 = apply(d, dm)
        print(f"virtual -> ({dm.dmPositionX},{dm.dmPositionY}) resultados {r1},{r2} (0 = ok)")
    if scale:
        set_vdd_scale(scale)
    for d, dm in active_displays():
        print(f"  {d.DeviceName} {dm.dmPelsWidth}x{dm.dmPelsHeight}@{dm.dmDisplayFrequency} pos=({dm.dmPositionX},{dm.dmPositionY}) {'primario' if d.StateFlags & 4 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
