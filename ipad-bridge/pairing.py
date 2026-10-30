"""Emparejamiento de visores: la PC muestra un código de 6 dígitos (QR en pc.html, bandeja); el visor lo manda una vez
y recibe un token que vale 30 días. Los tokens se guardan hasheados (SHA-256) en certs/pairing.json, junto con el `id`
estable de esta PC (el que se publica por mDNS). El archivo queda fuera de git.

Reglas: el código se regenera al arrancar el servidor y cada vez que se usa con éxito; tras 10 intentos fallidos
seguidos también se regenera (así no se puede probar el millón de combinaciones), y cada fallo espera 1 s.
"""
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

TOKEN_DAYS = 30
MAX_FAILURES = 10


class Pairing:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"id": None, "tokens": []}
        self.code = None
        self.failures = 0
        self._load()
        if not self.data.get("id"):
            self.data["id"] = secrets.token_hex(6)      # 12 hex: estable mientras exista pairing.json
            self._save()
        self.new_code()

    # ---------------------------------------------------------------- archivo

    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("tokens"), list):
                self.data = d
        except (OSError, ValueError):
            pass

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def pc_id(self):
        return self.data["id"]

    # ---------------------------------------------------------------- código

    def new_code(self):
        self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.failures = 0
        return self.code

    def check_code(self, code):
        """True si el código es el vigente. Cada acierto lo renueva; 10 fallos seguidos también."""
        ok = isinstance(code, str) and hmac.compare_digest(code.strip(), self.code)
        if ok:
            self.new_code()
        else:
            self.failures += 1
            if self.failures >= MAX_FAILURES:
                self.new_code()
        return ok

    # ---------------------------------------------------------------- tokens

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _purge(self):
        now = time.time()
        before = len(self.data["tokens"])
        self.data["tokens"] = [t for t in self.data["tokens"] if t.get("expires", 0) > now]
        return len(self.data["tokens"]) != before

    def issue(self, name=""):
        """Emite un token nuevo (32 bytes aleatorios) para un visor que acertó el código. Devuelve (token, expires)."""
        self._purge()
        token = secrets.token_urlsafe(32)
        now = time.time()
        entry = {"hash": self._hash(token), "name": str(name or "")[:64], "created": now,
                 "expires": now + TOKEN_DAYS * 86400, "last": now}
        self.data["tokens"].append(entry)
        self._save()
        return token, entry["expires"]

    def check_token(self, token):
        """Entrada del token si es válido y no venció, si no None. Actualiza `last` (a lo sumo una vez por hora)."""
        if not isinstance(token, str) or not token:
            return None
        changed = self._purge()
        h = self._hash(token)
        found = None
        for t in self.data["tokens"]:
            if hmac.compare_digest(t.get("hash", ""), h):
                found = t
        if found and time.time() - found.get("last", 0) > 3600:
            found["last"] = time.time()
            changed = True
        if changed:
            self._save()
        return found

    def revoke_all(self):
        self.data["tokens"] = []
        self._save()

    def paired(self):
        """Lista de visores emparejados (nombre y vencimiento), para la página de estado y la bandeja."""
        self._purge()
        return [{"name": t.get("name", ""), "expires": t.get("expires", 0), "last": t.get("last", 0)}
                for t in self.data["tokens"]]
