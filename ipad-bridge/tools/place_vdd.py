"""Ubica el monitor virtual: python tools/place_vdd.py left|right [desplazamiento_y] [--hz=120]"""
import ctypes, sys
from ctypes import wintypes
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import winput  # activa DPI awareness: todo en píxeles físicos

user32 = ctypes.windll.user32
CDS_UPDATEREGISTRY, CDS_NORESET, DM_POSITION = 0x1, 0x10000000, 0x20


class DEVMODE(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD), ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long), ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128), ("StateFlags", wintypes.DWORD), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


def active_displays():
    out, i = [], 0
    while True:
        d = DISPLAY_DEVICE(); d.cb = ctypes.sizeof(d)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        if d.StateFlags & 1:
            dm = DEVMODE(); dm.dmSize = ctypes.sizeof(dm)
            user32.EnumDisplaySettingsW(d.DeviceName, -1, ctypes.byref(dm))
            out.append((d, dm))
        i += 1
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--hz=")]
    hz = next((int(a[5:]) for a in sys.argv[1:] if a.startswith("--hz=")), None)
    side = args[0] if args else "left"
    dy = int(args[1]) if len(args) > 1 else None
    disps = active_displays()
    primary = next((dm for d, dm in disps if d.StateFlags & 4), None)
    virt = next(((d, dm) for d, dm in disps if "Virtual Display" in d.DeviceString), None)
    if primary is None or virt is None:
        print("no encuentro el monitor principal o el virtual"); return 1
    d, dm = virt
    pw, ph = primary.dmPelsWidth, primary.dmPelsHeight
    vw, vh = dm.dmPelsWidth, dm.dmPelsHeight
    dm.dmPositionX = -int(vw) if side == "left" else int(pw)
    dm.dmPositionY = dy if dy is not None else int((ph - vh) // 2)  # centrado verticalmente
    dm.dmFields = DM_POSITION
    if hz:
        DM_PELSWIDTH, DM_PELSHEIGHT, DM_DISPLAYFREQUENCY = 0x80000, 0x100000, 0x400000
        dm.dmDisplayFrequency = hz
        dm.dmFields |= DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
    r1 = user32.ChangeDisplaySettingsExW(d.DeviceName, ctypes.byref(dm), None, CDS_UPDATEREGISTRY | CDS_NORESET, None)
    r2 = user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    print(f"virtual -> ({dm.dmPositionX},{dm.dmPositionY}) resultados {r1},{r2} (0 = ok)")
    for d, dm in active_displays():
        print(f"  {d.DeviceName} {dm.dmPelsWidth}x{dm.dmPelsHeight}@{dm.dmDisplayFrequency} pos=({dm.dmPositionX},{dm.dmPositionY}) {'primario' if d.StateFlags & 4 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
