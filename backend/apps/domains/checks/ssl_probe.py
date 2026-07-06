"""TLS certificate probe — read the leaf certificate WITHOUT verifying it.

``CERT_NONE`` + ``getpeercert(binary_form=True)`` so expired/self-signed certs
still return their metadata; a verifying handshake would abort on exactly the
certificates we most need to report. The DER blob is parsed with
``cryptography.x509`` (already a project dependency).

Like every module in this package: pure functions, no model imports, never
raises — always returns ``{"status": ..., ...}`` (values from
``DomainInfo.CheckStatus``); failures carry the exception class name only.
"""

import socket
import ssl

from cryptography import x509


def _name(x509_name) -> str:
    return x509_name.rfc4514_string()[:255]


def probe_ssl(host: str, *, port: int = 443, timeout: float = 10.0) -> dict:
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}

    if not der:
        return {"status": "error", "error": "NoCertificate"}
    try:
        cert = x509.load_der_x509_certificate(der)
        return {
            "status": "ok",
            "issuer": _name(cert.issuer),
            "subject": _name(cert.subject),
            "not_before": cert.not_valid_before_utc,
            "not_after": cert.not_valid_after_utc,
        }
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
