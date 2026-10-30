"""Banco de pruebas de movimiento: ventana con formas rebotando y texto, movimiento determinista a 60 Hz, para medir
Mbps y fps con contenido en movimiento siempre igual. Uso: python tools/motion_test.py [segundos=30] [ancho] [alto] [x] [y]
Se abre en el monitor principal (o donde indiquen x,y: p. ej. -2732 0 para el monitor virtual a la izquierda)."""
import random
import sys
import tkinter as tk

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)   # píxeles físicos: la ventana queda exactamente donde se pide

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
W = int(sys.argv[2]) if len(sys.argv) > 2 else 1600
H = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
X = int(sys.argv[4]) if len(sys.argv) > 4 else 100
Y = int(sys.argv[5]) if len(sys.argv) > 5 else 100

root = tk.Tk()
root.title("iPad Bridge: prueba de movimiento")
root.geometry(f"{W}x{H}+{X}+{Y}")
root.attributes("-topmost", True)
cv = tk.Canvas(root, width=W, height=H, bg="#f4f4f4", highlightthickness=0)
cv.pack(fill="both", expand=True)
rng = random.Random(7)
shapes = []
for i in range(40):
    x, y = rng.randint(0, W - 200), rng.randint(0, H - 200)
    col = "#%02x%02x%02x" % (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
    s = rng.randint(60, 220)
    item = cv.create_oval(x, y, x + s, y + s, fill=col, outline="") if i % 2 else cv.create_rectangle(x, y, x + s, y + s, fill=col, outline="")
    shapes.append([item, x, y, rng.choice([-9, -6, 6, 9]), rng.choice([-7, -5, 5, 7]), s])
text = cv.create_text(20, 20, anchor="nw", text="", font=("Consolas", 28), fill="#111")
frame = 0


def tick():
    global frame
    frame += 1
    for sh in shapes:
        item, x, y, dx, dy, s = sh
        x += dx
        y += dy
        if x < 0 or x + s > W:
            dx = -dx
        if y < 0 or y + s > H:
            dy = -dy
        sh[1:5] = x, y, dx, dy
        cv.coords(item, x, y, x + s, y + s)
    cv.itemconfigure(text, text=f"frame {frame:05d}  " + "texto nítido para ver la calidad " * 2)
    if frame < secs * 60:
        root.after(16, tick)
    else:
        root.destroy()


root.after(16, tick)
root.mainloop()
