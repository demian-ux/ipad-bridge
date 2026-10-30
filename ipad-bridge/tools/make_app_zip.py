"""Regenera static/iPadBridge.swiftpm.zip a partir de app/iPadBridge.swiftpm.

Las rutas dentro del zip van con barras "/" (Compress-Archive de PowerShell las escribe con "\\" y la app Archivos
del iPad las toma como un solo nombre de archivo, con lo que Playgrounds no abre el paquete). Entradas ordenadas y con
la fecha de cada archivo, así el zip solo cambia cuando cambian las fuentes.

Uso:  python tools/make_app_zip.py            # solo si alguna fuente es más nueva que el zip
      python tools/make_app_zip.py --force    # siempre
server.py lo llama al arrancar (build_if_stale) para que la descarga de la página de instalación esté al día."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app" / "iPadBridge.swiftpm"
ZIP_PATH = ROOT / "static" / "iPadBridge.swiftpm.zip"
SKIP_DIRS = {".build", ".swiftpm", "xcuserdata"}     # lo que Playgrounds o Xcode generan al abrir el paquete


def sources(app_dir=APP_DIR):
    """Archivos del paquete, en orden fijo, sin ocultos ni carpetas de compilación."""
    out = []
    for p in sorted(app_dir.rglob("*")):
        rel = p.relative_to(app_dir)
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_file():
            out.append(p)
    return out


def is_stale(app_dir=APP_DIR, zip_path=ZIP_PATH):
    """True si falta el zip, si alguna fuente es más nueva o si el conjunto de archivos no coincide."""
    if not zip_path.exists():
        return True
    srcs = sources(app_dir)
    if not srcs:
        return False
    zmtime = zip_path.stat().st_mtime
    if any(p.stat().st_mtime > zmtime for p in srcs):
        return True
    want = {f"{app_dir.name}/{p.relative_to(app_dir).as_posix()}" for p in srcs}
    try:
        with zipfile.ZipFile(zip_path) as z:
            have = {i.filename for i in z.infolist() if not i.filename.endswith("/")}
    except zipfile.BadZipFile:
        return True
    return have != want


def build(app_dir=APP_DIR, zip_path=ZIP_PATH):
    """Escribe el zip (rutas con "/", carpeta raíz app_dir.name). Devuelve la lista de rutas incluidas."""
    srcs = sources(app_dir)
    if not srcs:
        raise FileNotFoundError(f"no hay fuentes en {app_dir}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_suffix(".zip.tmp")
    names = []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo(f"{app_dir.name}/", date_time=_zip_time(app_dir)), b"")
        for p in srcs:
            name = f"{app_dir.name}/{p.relative_to(app_dir).as_posix()}"
            info = zipfile.ZipInfo(name, date_time=_zip_time(p))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
            names.append(name)
    tmp.replace(zip_path)
    return names


def build_if_stale(app_dir=APP_DIR, zip_path=ZIP_PATH):
    """Regenera solo si hace falta. Devuelve las rutas escritas, o None si el zip ya estaba al día."""
    if not is_stale(app_dir, zip_path):
        return None
    return build(app_dir, zip_path)


def _zip_time(p):
    import time
    t = time.localtime(max(p.stat().st_mtime, 315532800))   # el formato zip no admite fechas anteriores a 1980
    return (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


if __name__ == "__main__":
    force = "--force" in sys.argv[1:]
    names = build() if force else build_if_stale()
    if names is None:
        print(f"{ZIP_PATH.name} ya está al día ({len(sources())} archivos)")
    else:
        print(f"{ZIP_PATH} regenerado con {len(names)} archivos:")
        for n in names:
            print("  " + n)
