import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pydantic import SecretStr

from app.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Keep unit tests independent of workstation credentials and dotenv files.
    import os

    for name in list(os.environ):
        if name.startswith("TRACKING_"):
            monkeypatch.delenv(name)
    import base64

    monkeypatch.setenv("TRACKING_AUTH_SECRET", "ab" * 32)
    monkeypatch.setenv("TRACKING_OTP_SECRET", "cd" * 32)
    monkeypatch.setenv("TRACKING_MAIL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    return Settings(
        _env_file=None,
        database_password=SecretStr("synthetic-unit-test-password"),
    )


def _pem(path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


# A synthetic certificate authority for domain-verification tests (specification 005-E). Keys
# and certificates are generated per test session in a temporary directory; nothing is trusted
# outside the explicit test contexts that load this CA.
@pytest.fixture(scope="session")
def synthetic_pki(tmp_path_factory):
    directory = tmp_path_factory.mktemp("synthetic-pki")
    now = datetime.now(UTC)

    def authority(label: str):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Synthetic {label} CA")])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=60))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .sign(key, hashes.SHA256())
        )
        return key, certificate

    trusted = authority("trusted")
    untrusted = authority("untrusted")
    ca_path = _pem(directory / "ca.pem", trusted[1].public_bytes(serialization.Encoding.PEM))
    issued = 0

    def issue(hostname: str, *, valid_for=timedelta(days=30), age=timedelta(days=1), ca=trusted):
        nonlocal issued
        issued += 1
        key = ec.generate_private_key(ec.SECP256R1())
        start = now - age
        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(ca[1].subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(start)
            .not_valid_after(now + valid_for)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca[0].public_key()),
                critical=False,
            )
            .sign(ca[0], hashes.SHA256())
        )
        cert_path = _pem(
            directory / f"leaf-{issued}.pem", certificate.public_bytes(serialization.Encoding.PEM)
        )
        key_path = _pem(
            directory / f"leaf-{issued}.key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        return SimpleNamespace(cert=cert_path, key=key_path, not_after=now + valid_for)

    return SimpleNamespace(
        ca=ca_path,
        issue=issue,
        untrusted=untrusted,
        context=lambda: ssl.create_default_context(cafile=ca_path),
    )


# Loopback TLS servers presenting synthetic certificates. Each records the SNI names it saw and
# any application bytes a client sent after the handshake (a verifier must send none).
@pytest.fixture
def tls_server():
    servers = []

    def start(certificate):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate.cert, certificate.key)
        context.num_tickets = 0  # no post-handshake writes to a client that has already closed
        state = SimpleNamespace(names=[], data=[], handshakes=0)

        def remember(_connection, name, _context):
            state.names.append(name)

        context.sni_callback = remember
        listener = socket.create_server(("127.0.0.1", 0))
        listener.settimeout(0.2)
        stop = threading.Event()

        def serve():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                try:
                    connection.settimeout(2)
                    with context.wrap_socket(connection, server_side=True) as secure:
                        state.handshakes += 1
                        try:
                            state.data.append(secure.recv(1024))
                        except (ssl.SSLError, ConnectionError):
                            state.data.append(b"")
                except (ssl.SSLError, OSError):
                    connection.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        state.port = listener.getsockname()[1]
        servers.append((stop, listener, thread))
        return state

    yield start
    for stop, listener, thread in servers:
        stop.set()
        listener.close()
        thread.join(timeout=5)
