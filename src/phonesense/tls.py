"""Self-signed TLS certificate, generated in pure Python (no system openssl).

The phone's camera APIs require HTTPS, so the server needs a cert. Shelling out
to ``openssl`` is fragile on student laptops (often absent on Windows), so we
build the cert with the ``cryptography`` library instead.

The cert is written once to a stable, writable per-user data dir (so a `uvx`
run — whose wheel dir is ephemeral and read-only — doesn't regenerate it every
launch and re-trigger the phone's cert warning) and reused on later runs.
"""

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from platformdirs import user_data_dir

CERT_NAME = "phonesense.local"
VALID_DAYS = 825  # browsers reject leaf certs valid for much longer


def default_cert_dir() -> Path:
    """Stable, writable place to keep the cert across runs."""
    return Path(user_data_dir("phonesense"))


def ensure_cert(lan_ips, cert_dir=None):
    """Return (cert_path, key_path), generating the pair on first run.

    ``lan_ips`` is one IP string or an iterable of them; each goes into the cert's
    SAN so the phone validates against the same cert whichever advertised address
    it connects to. Once written, the pair is reused (no regeneration) on later runs.
    """
    if isinstance(lan_ips, str):
        lan_ips = [lan_ips]
    cert_dir = Path(cert_dir) if cert_dir is not None else default_cert_dir()
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CERT_NAME)])
    # Validity is anchored a day in the past to tolerate minor clock skew.
    not_before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    not_after = not_before + datetime.timedelta(days=VALID_DAYS + 1)

    san = [
        x509.DNSName("localhost"),
        x509.DNSName(CERT_NAME),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    for lan_ip in lan_ips:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
        except ValueError:
            pass  # not a literal IP; the DNS entries still cover localhost

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    # Key is sensitive; restrict where the OS allows it (no-op on Windows).
    try:
        key_path.chmod(0o600)
    except OSError:
        pass

    return cert_path, key_path
