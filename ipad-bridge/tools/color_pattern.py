"""Patrón estático para medir fidelidad de color (ΔE) del pipeline: degradados, parches saturados, texto fino y una
trama de 1 px, en una ventana sin bordes en (x, y) de tamaño fijo, para recortar lo mismo en la captura cruda y en el
frame decodificado. Uso: python tools/color_pattern.py [segundos=30] [x=100] [y=100]   (ventana de 1400x900)"""
import sys
import tkinter as tk

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)   # píxeles físicos: la ventana queda exactamente donde se pide

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
X = int(sys.argv[2]) if len(sys.argv) > 2 else 100
Y = int(sys.argv[3]) if len(sys.argv) > 3 else 100
W, H = 1400, 900

root = tk.Tk()
root.overrideredirect(True)
root.geometry(f"{W}x{H}+{X}+{Y}")
root.attributes("-topmost", True)
cv = tk.Canvas(root, width=W, height=H, bg="#ffffff", highlightthickness=0)
cv.pack()
# Degradados horizontales (R, G, B, gris) de 256 pasos
for i in range(256):
    x0 = 20 + i * 5
    cv.create_rectangle(x0, 20, x0 + 5, 80, fill="#%02x0000" % i, outline="")
    cv.create_rectangle(x0, 90, x0 + 5, 150, fill="#00%02x00" % i, outline="")
    cv.create_rectangle(x0, 160, x0 + 5, 220, fill="#0000%02x" % i, outline="")
    cv.create_rectangle(x0, 230, x0 + 5, 290, fill="#%02x%02x%02x" % (i, i, i), outline="")
# Parches saturados y tonos de piel (donde el 4:2:0 más se nota)
patches = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff", "#ff8000", "#8000ff", "#f1c27d", "#e0ac69", "#8d5524", "#c68642"]
for i, c in enumerate(patches):
    cv.create_rectangle(20 + i * 110, 310, 120 + i * 110, 410, fill=c, outline="")
# Texto fino en varios colores sobre fondos distintos
for i, (fg, bg) in enumerate([("#000", "#fff"), ("#fff", "#000"), ("#f00", "#00f"), ("#0a0", "#fee"), ("#333", "#ddd")]):
    cv.create_rectangle(20, 430 + i * 60, 1380, 485 + i * 60, fill=bg, outline="")
    cv.create_text(30, 457 + i * 60, anchor="w", text="Texto fino: el iPad como pantalla extendida 0123456789 ÁÉÍÓÚ ñ — " * 2,
                   fill=fg, font=("Segoe UI", 14))
# Trama de 1 px (líneas alternadas): lo peor para el 4:2:0 con color
for y in range(740, 880, 2):
    cv.create_line(20, y, 700, y, fill="#ff0000")
    cv.create_line(720, y, 1380, y, fill="#0000ff")
    cv.create_line(20, y + 1, 700, y + 1, fill="#00ff00")
root.after(int(secs * 1000), root.destroy)
root.mainloop()
