"""Reloj en pantalla para medir cuánto tarda un píxel en salir del encoder (captura -> ts del frame).
Dibuja, sin bordes, en (X,Y) del escritorio, una fila de 32 cuadrados blancos/negros con los bits de
perf_counter() en ms (reloj QPC, el mismo en todos los procesos de la PC) y la redibuja todo el tiempo.
Uso: python tools/latency_clock.py [segundos=20] [x=100] [y=100]
Medición: tools/latency_measure.py (dump del flujo con stream_probe + decodificación + lectura de los cuadrados)."""
import sys
import time
import tkinter as tk

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)   # píxeles físicos: la ventana queda exactamente donde se pide

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
X = int(sys.argv[2]) if len(sys.argv) > 2 else 100
Y = int(sys.argv[3]) if len(sys.argv) > 3 else 100
SQ, BITS = 40, 32
W, H = SQ * (BITS + 2), SQ * 3

root = tk.Tk()
root.overrideredirect(True)          # sin barra de título: el área de cliente queda exactamente en (X, Y)
root.geometry(f"{W}x{H}+{X}+{Y}")
root.attributes("-topmost", True)
cv = tk.Canvas(root, width=W, height=H, bg="#808080", highlightthickness=0)
cv.pack()
# Marcas de sincronismo: primer cuadrado negro, último blanco (para comprobar que leemos la fila correcta).
cv.create_rectangle(0, SQ, SQ, 2 * SQ, fill="#000", outline="")
cv.create_rectangle((BITS + 1) * SQ, SQ, (BITS + 2) * SQ, 2 * SQ, fill="#fff", outline="")
cells = [cv.create_rectangle((i + 1) * SQ, SQ, (i + 2) * SQ, 2 * SQ, fill="#000", outline="") for i in range(BITS)]
t0 = time.perf_counter()


def tick():
    ms = int(time.perf_counter() * 1000) & 0xFFFFFFFF
    for i in range(BITS):
        cv.itemconfigure(cells[i], fill="#fff" if (ms >> (BITS - 1 - i)) & 1 else "#000")
    if time.perf_counter() - t0 < secs:
        root.after(1, tick)
    else:
        root.destroy()


root.after(1, tick)
root.mainloop()
