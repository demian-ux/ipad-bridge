"""Mide la fidelidad de color de un pipeline: ΔE (CIE76, Lab D65) entre la captura cruda del monitor virtual y lo que
llegaría al iPad tras encodear y decodificar. Uso: python tools/color_check.py raw.png decodificado.png [etiqueta]
ΔE < 1: indistinguible. 1-2: apenas perceptible lado a lado. > 3: visible."""
import sys
import numpy as np
from PIL import Image


def srgb_to_lab(c):
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T
    wp = np.array([0.95047, 1.0, 1.08883])  # D65
    r = xyz / wp
    f = np.where(r > 0.008856, np.cbrt(r), 7.787 * r + 16 / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def load(path, size=None):
    """PNG de 8 bits, o .rgb48 crudo (ffmpeg -f rawvideo -pix_fmt rgb48le) para medir 10 bits sin perder precisión."""
    if path.endswith(".rgb48"):
        w, h = size
        return np.fromfile(path, dtype="<u2").reshape(h, w, 3).astype(np.float64) / 65535.0
    im = Image.open(path)
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    return np.asarray(im, dtype=np.float64)[:, :, :3] / 255.0


def main():
    raw = load(sys.argv[1])
    dec = load(sys.argv[2], (raw.shape[1], raw.shape[0]))
    label = sys.argv[3] if len(sys.argv) > 3 else sys.argv[2]
    d = np.linalg.norm(srgb_to_lab(raw) - srgb_to_lab(dec), axis=-1)
    # Ignorar el cursor y bordes de 1 px de ventanas: percentiles en vez de máximo puro.
    print(f"{label:28s} ΔE medio {d.mean():5.2f} · p95 {np.percentile(d, 95):5.2f} · p99.9 {np.percentile(d, 99.9):5.2f} "
          f"· píxeles con ΔE>2: {100 * (d > 2).mean():5.2f}% · ΔE>5: {100 * (d > 5).mean():5.2f}%")


if __name__ == "__main__":
    main()
