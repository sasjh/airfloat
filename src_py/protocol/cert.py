"""Self-signed RSA-2048 X.509 certificate generation using ``cryptography``.

LocalSend v2 fingerprint = SHA-256 (hex) of the certificate DER bytes.
"""

import datetime
import hashlib
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

_CN = "AirFloat"


def create_self_signed():
    """Generate a self-signed RSA-2048 certificate.

    Returns a dict with keys: ``cert_der`` (bytes), ``pem`` (str),
    ``key`` (str, PKCS#8 PEM) and ``fingerprint`` (hex SHA-256 of DER).
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _CN)])

    now = datetime.datetime.now(datetime.timezone.utc)
    not_before = now - datetime.timedelta(days=1)
    not_after = now + datetime.timedelta(days=365 * 10)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )

    cert_der = cert.public_bytes(serialization.Encoding.DER)
    pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")

    return {
        "cert_der": cert_der,
        "pem": pem,
        "key": key_pem,
        "fingerprint": fingerprint_from_der(cert_der),
    }


def fingerprint_from_der(cert_der):
    """SHA-256 (hex) of the certificate DER bytes."""
    if isinstance(cert_der, str):
        cert_der = cert_der.encode("utf-8")
    return hashlib.sha256(cert_der).hexdigest()


def random_fingerprint():
    """Random 256-bit hex string (HTTP mode fingerprint)."""
    return os.urandom(32).hex()
