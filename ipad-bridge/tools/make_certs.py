"""Genera certs/ca.crt (CA propia, 10 años) y certs/server.crt para la IP local (1 año, SAN con IP y localhost).
Sin openssl: usa el paquete `cryptography`. La CA se reutiliza si ya existe (el iPad confía en ella una sola vez);
el certificado del servidor se reemite si falta, venció o cambió la IP.   Uso: python tools/make_certs.py [IP]"""
import datetime as dt
import ipaddress
import socket
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERTS = Path(__file__).resolve().parent.parent / "certs"


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def write(path, data):
    path.write_bytes(data)


def load_or_make_ca():
    key_p, crt_p = CERTS / "ca.key", CERTS / "ca.crt"
    if key_p.exists() and crt_p.exists():
        key = serialization.load_pem_private_key(key_p.read_bytes(), None)
        return key, x509.load_pem_x509_certificate(crt_p.read_bytes()), False
    key = rsa.generate_private_key(65537, 2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "iPad Bridge CA")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    write(key_p, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                   serialization.NoEncryption()))
    write(crt_p, cert.public_bytes(serialization.Encoding.PEM))
    return key, cert, True


def server_cert_ok(ip):
    p = CERTS / "server.crt"
    if not p.exists() or not (CERTS / "server.key").exists():
        return False
    cert = x509.load_pem_x509_certificate(p.read_bytes())
    if cert.not_valid_after_utc < dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
        return False
    try:
        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return ipaddress.ip_address(ip) in sans.get_values_for_type(x509.IPAddress)
    except x509.ExtensionNotFound:
        return False


def make_server(ca_key, ca_cert, ip):
    key = rsa.generate_private_key(65537, 2048)
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "iPad Bridge")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))        # <= 398 días: requisito de iOS
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                                                        x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    write(CERTS / "server.key", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                  serialization.NoEncryption()))
    write(CERTS / "server.crt", cert.public_bytes(serialization.Encoding.PEM))


def main():
    CERTS.mkdir(exist_ok=True)
    ip = sys.argv[1] if len(sys.argv) > 1 else local_ip()
    ca_key, ca_cert, new_ca = load_or_make_ca()
    print(f"CA: {'creada' if new_ca else 'existente'} ({CERTS / 'ca.crt'})")
    if server_cert_ok(ip):
        print(f"certificado del servidor vigente para {ip}")
    else:
        make_server(ca_key, ca_cert, ip)
        print(f"certificado del servidor emitido para {ip} (1 año)")
    if new_ca:
        print("Nuevo CA: cada iPad tiene que instalarlo una vez desde http://%s/" % ip)


if __name__ == "__main__":
    main()
