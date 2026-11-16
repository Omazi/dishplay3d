"""Self-signed TLS certificate for the local calculator, pinned by the app.

The iPhone receives the SHA-256 fingerprint of the certificate (DER) in the
pairing QR code and accepts the server ONLY if it presents exactly this
certificate. Certificate validation is therefore not disabled: it is replaced
by an explicit pin.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def ensure_certificate(directory: Path, ips: list[str]) -> tuple[Path, Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    cert_p, key_p = directory / "server.crt", directory / "server.key"
    if cert_p.exists() and key_p.exists():
        cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        have = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
        if set(ips) <= have and cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
            return cert_p, key_p, fingerprint(cert_p)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DishPlay Scan local calculator")])
    now = dt.datetime.now(dt.timezone.utc)
    alt = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(set(ips) | {"127.0.0.1"})]
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        key_p.chmod(0o600)
    except OSError:
        pass
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p, fingerprint(cert_p)


def fingerprint(cert_path: Path) -> str:
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
