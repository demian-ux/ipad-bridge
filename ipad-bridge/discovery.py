"""Descubrimiento por mDNS/Bonjour: publica `_ipadbridge._tcp` para que la app nativa liste las PCs sin escribir la IP.
TXT: id (estable, el de pairing.json), name (nombre de la PC), ip, http y https (puertos), ver (versión del protocolo).
La página web no puede usar mDNS: para ella queda el QR de pc.html. Si falta `zeroconf`, el servidor sigue sin publicar."""
import logging
import re
import socket

log = logging.getLogger("mdns")
SERVICE = "_ipadbridge._tcp.local."
PROTO_VER = "1"


def pc_name():
    return socket.gethostname().split(".")[0] or "PC"


class Advertiser:
    def __init__(self, pc_id, ip, http_port, tls_port, name=None):
        self.zc = None
        self.info = None
        self.name = name or pc_name()
        self.pc_id, self.ip, self.http_port, self.tls_port = pc_id, ip, http_port, tls_port

    async def start(self):
        """Registra el servicio con AsyncZeroconf (la versión síncrona no se puede llamar desde el loop de aiohttp)."""
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError:
            log.warning("sin zeroconf: no se publica por mDNS (pip install zeroconf)")
            return False
        label = re.sub(r"[^A-Za-z0-9 _-]", "", self.name)[:40] or "PC"
        props = {"id": self.pc_id, "name": self.name, "ip": self.ip, "http": str(self.http_port),
                 "https": str(self.tls_port), "ver": PROTO_VER}
        self.info = ServiceInfo(SERVICE, f"{label}._ipadbridge._tcp.local.", addresses=[socket.inet_aton(self.ip)],
                                port=self.tls_port, properties=props, server=f"{label.replace(' ', '-')}.local.")
        try:
            self.zc = AsyncZeroconf()
            await self.zc.async_register_service(self.info)
        except OSError as e:
            log.warning("mDNS no disponible: %s", e)
            self.zc = None
            return False
        log.info("mDNS: %s publicado como %s (id %s, %s)", SERVICE, label, self.pc_id, self.ip)
        return True

    async def update(self, ip):
        """La IP de la PC cambió: volver a publicar con la nueva dirección."""
        if self.zc is None or ip == self.ip:
            return
        await self.stop()
        self.ip = ip
        await self.start()

    async def stop(self):
        if self.zc is not None:
            try:
                await self.zc.async_unregister_service(self.info)
                await self.zc.async_close()
            except Exception:
                pass
            self.zc = None
