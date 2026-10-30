"""Ventana de prueba del lápiz: muestra en vivo lo que Windows entrega por WM_POINTER (tipo, presión 0..1024,
inclinación, banderas, botones) y las teclas que llegan (WM_KEYDOWN / WM_CHAR). Para probar el lápiz virtual, la
curva de presión, los gestos y el teclado del iPad sin una app de dibujo: dejala en primer plano sobre el monitor
que va al iPad y dibujá. Cada evento se imprime también en la consola.

Uso: python tools/pen_probe.py            (ventana en el monitor objetivo, el virtual si existe)
     python tools/pen_probe.py --top      (siempre encima: para pruebas automáticas sin iPad)
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from winput import POINTER_PEN_INFO, target_display  # noqa: E402

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    user32.SetProcessDPIAware()

WM_DESTROY, WM_PAINT, WM_KEYDOWN, WM_SYSKEYDOWN, WM_CHAR = 0x0002, 0x000F, 0x0100, 0x0104, 0x0102
WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x0201, 0x0204, 0x0207, 0x020A, 0x020E
WM_POINTERUPDATE, WM_POINTERDOWN, WM_POINTERUP, WM_POINTERENTER, WM_POINTERLEAVE = 0x0245, 0x0246, 0x0247, 0x0249, 0x024A
PT_POINTER, PT_TOUCH, PT_PEN, PT_MOUSE, PT_TOUCHPAD = 1, 2, 3, 4, 5
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.BeginPaint.restype = wt.HDC
user32.GetMessageExtraInfo.restype = wt.LPARAM
gdi32.CreatePen.restype = wt.HPEN
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.TextOutW.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int]
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
gdi32.MoveToEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.LineTo.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateSolidBrush.restype = wt.HBRUSH
user32.EndPaint.argtypes = [wt.HWND, ctypes.c_void_p]
user32.LoadCursorW.restype = wt.HANDLE


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT), ("fRestore", wt.BOOL),
                ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


lines = ["Dibujá con el Pencil desde el iPad. Esc cierra."]
stroke = []        # puntos (x, y, presión) del trazo actual, en coordenadas de la ventana
strokes = []
stats = {"down": 0, "updates": 0, "pmax": 0}
hwnd_main = None


def log(s):
    print(s, flush=True)
    lines.append(s)
    del lines[:-14]
    if hwnd_main:
        user32.InvalidateRect(hwnd_main, None, True)


def pen_info(wparam):
    pid = wparam & 0xFFFF
    info = POINTER_PEN_INFO()
    if user32.GetPointerPenInfo(pid, ctypes.byref(info)):
        return info
    return None


def pointer_type(wparam):
    t = ctypes.c_uint32()
    user32.GetPointerType(wparam & 0xFFFF, ctypes.byref(t))
    return t.value


def wndproc(hwnd, msg, wparam, lparam):
    global stroke
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    if msg in (WM_POINTERDOWN, WM_POINTERUPDATE, WM_POINTERUP, WM_POINTERENTER, WM_POINTERLEAVE):
        pt = pointer_type(wparam)
        name = {PT_PEN: "pen", PT_TOUCH: "touch", PT_MOUSE: "mouse", PT_TOUCHPAD: "touchpad"}.get(pt, str(pt))
        if pt == PT_PEN:
            info = pen_info(wparam)
            if info is not None:
                pi = info.pointerInfo
                p = wt.POINT(pi.ptPixelLocation.x, pi.ptPixelLocation.y)
                user32.ScreenToClient(hwnd, ctypes.byref(p))
                if msg == WM_POINTERDOWN:
                    stats["down"] += 1
                    stroke = []
                    strokes.append(stroke)
                    del strokes[:-20]
                if msg in (WM_POINTERDOWN, WM_POINTERUPDATE) and pi.pointerFlags & 0x4:   # INCONTACT
                    stats["updates"] += 1
                    stats["pmax"] = max(stats["pmax"], info.pressure)
                    stroke.append((p.x, p.y, info.pressure))
                    if stats["updates"] % 8 == 1 or msg == WM_POINTERDOWN:
                        log(f"{'DOWN' if msg == WM_POINTERDOWN else 'move'} pen ({pi.ptPixelLocation.x},{pi.ptPixelLocation.y}) "
                            f"presión {info.pressure}/1024 tilt {info.tiltX},{info.tiltY} penFlags {info.penFlags} "
                            f"flags 0x{pi.pointerFlags:x}")
                elif msg == WM_POINTERUP:
                    log(f"UP   pen ({pi.ptPixelLocation.x},{pi.ptPixelLocation.y}) puntos del trazo: {len(stroke)} "
                        f"presión máx. {max([s[2] for s in stroke] or [0])}")
                elif msg == WM_POINTERENTER:
                    log("ENTER pen (en alcance)")
                elif msg == WM_POINTERLEAVE:
                    log("LEAVE pen (fuera de alcance)")
                elif msg == WM_POINTERUPDATE:
                    pass   # hover: no llenar la consola
                user32.InvalidateRect(hwnd, None, True)
                return 0
        elif msg in (WM_POINTERDOWN, WM_POINTERUP):
            log(f"{'DOWN' if msg == WM_POINTERDOWN else 'UP'} {name}")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    if msg in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
        src = user32.GetMessageExtraInfo()
        btn = {WM_LBUTTONDOWN: "izquierdo", WM_RBUTTONDOWN: "derecho", WM_MBUTTONDOWN: "medio"}[msg]
        log(f"mouse {btn} ({lparam & 0xFFFF},{(lparam >> 16) & 0xFFFF}) extra 0x{src & 0xFFFFFFFF:x}")
        return 0
    if msg in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
        delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
        log(f"rueda {'horizontal' if msg == WM_MOUSEHWHEEL else 'vertical'} {delta}")
        return 0
    if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
        if wparam == 0x1B:
            user32.DestroyWindow(hwnd)
            return 0
        mods = "".join(m for vk, m in ((0x11, "ctrl+"), (0x10, "shift+"), (0x12, "alt+"), (0x5B, "win+"))
                       if user32.GetKeyState(vk) & 0x8000)
        name = {0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down", 0x24: "home", 0x23: "end", 0x21: "pageup",
                0x22: "pagedown", 0x2E: "delete", 0x2D: "insert", 0x0D: "enter", 0x08: "backspace", 0x09: "tab",
                0x20: "space"}.get(wparam)
        if name is None and 0x70 <= wparam <= 0x87:
            name = f"f{wparam - 0x6F}"
        if name is None and 0x60 <= wparam <= 0x69:
            name = f"num{wparam - 0x60}"
        if name is None and wparam not in (0x10, 0x11, 0x12, 0x5B):
            name = f"vk 0x{wparam:02x}"
        if name:
            log(f"tecla {mods}{name}" + (" (extendida)" if (lparam >> 24) & 1 else ""))
        return 0
    if msg == WM_CHAR:
        ch = chr(wparam)
        if ch.isprintable():
            log(f"carácter {ch!r}")
        return 0
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        rc = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        gdi32.SetBkMode(hdc, 1)
        gdi32.SetTextColor(hdc, 0x00DDDDDD)
        y = 8
        head = f"pen_probe  trazos {stats['down']}  puntos {stats['updates']}  presión máx. {stats['pmax']}/1024"
        gdi32.TextOutW(hdc, 8, y, head, len(head))
        for s in lines:
            y += 18
            gdi32.TextOutW(hdc, 8, y, s, len(s))
        # Trazos: grosor según la presión recibida (como lo haría una app de dibujo)
        for st in strokes:
            for i in range(1, len(st)):
                w = max(1, int(st[i][2] / 1024 * 24))
                pen = gdi32.CreatePen(0, w, 0x0000FF00 if st is stroke else 0x0000AA66)
                old = gdi32.SelectObject(hdc, pen)
                gdi32.MoveToEx(hdc, st[i - 1][0], st[i - 1][1], None)
                gdi32.LineTo(hdc, st[i][0], st[i][1])
                gdi32.SelectObject(hdc, old)
                gdi32.DeleteObject(pen)
        user32.EndPaint(hwnd, ctypes.byref(ps))
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    global hwnd_main
    proc = WNDPROC(wndproc)
    wc = WNDCLASS()
    wc.lpfnWndProc = proc
    wc.lpszClassName = "IpadBridgePenProbe"
    wc.hbrBackground = gdi32.CreateSolidBrush(0x00202020)
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
    user32.RegisterClassW(ctypes.byref(wc))
    t = target_display() or {"rect": (0, 0, 1200, 800)}
    l, tp, r, b = t["rect"]
    w, h = r - l, b - tp
    hwnd_main = user32.CreateWindowExW(0, wc.lpszClassName, "iPad Bridge: prueba del lápiz (Esc cierra)",
                                       0x00CF0000, l + w // 8, tp + h // 8, w * 3 // 4, h * 3 // 4, None, None, None, None)
    # Sin "mantener presionado = clic derecho" ni gestos de Windows en esta ventana: el lápiz llega crudo.
    user32.EnableMouseInPointer(False)
    if "--top" in sys.argv:
        user32.SetWindowPos(hwnd_main, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_TOPMOST, sin mover ni cambiar tamaño
    user32.ShowWindow(hwnd_main, 5)
    user32.SetForegroundWindow(hwnd_main)
    print(f"ventana en {t.get('name', '?')} {w}x{h}; esperando WM_POINTER…", flush=True)
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
