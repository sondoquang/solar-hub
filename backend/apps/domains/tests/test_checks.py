"""Unit tests for the pure lookup functions in apps/domains/checks.

No network: the httpx pool, dnspython resolver and the TLS socket handshake are
all faked. The SSL test parses a real (generated) certificate so the
cryptography-based DER parsing is exercised for real.
"""

from datetime import UTC, datetime, timedelta

import dns.resolver as dnsres
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from apps.domains.checks import (
    dns_lookup,
    dnsbl,
    google_index,
    http_pool,
    ssl_probe,
    tenten_provider,
    whois_lookup,
)

# --- shared fakes ---------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeRdata:
    def __init__(self, text):
        self._text = text

    def to_text(self):
        return self._text


class _FakeResolver:
    """resolve() answers from a {(name, rtype): [...texts] | Exception} table;
    unknown names raise NXDOMAIN (the DNS 'does not exist' answer)."""

    def __init__(self, table):
        self.table = table

    def resolve(self, name, rtype):
        value = self.table.get((name, rtype))
        if value is None:
            raise dnsres.NXDOMAIN()
        if isinstance(value, Exception):
            raise value
        return [_FakeRdata(v) for v in value]


# --- SSL -------------------------------------------------------------------


def _self_signed_der(not_before, not_after):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "shop.example.com")])
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
    return cert.public_bytes(serialization.Encoding.DER)


class _FakeSock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeTLS:
    def __init__(self, der):
        self._der = der

    def getpeercert(self, binary_form=False):
        return self._der

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_handshake(monkeypatch, der):
    monkeypatch.setattr(
        ssl_probe.socket, "create_connection", lambda *a, **k: _FakeSock()
    )
    monkeypatch.setattr(
        ssl_probe.ssl.SSLContext,
        "wrap_socket",
        lambda self, sock, server_hostname=None: _FakeTLS(der),
    )


def test_probe_ssl_parses_valid_cert(monkeypatch):
    now = datetime.now(UTC)
    der = _self_signed_der(now - timedelta(days=1), now + timedelta(days=90))
    _patch_handshake(monkeypatch, der)
    result = ssl_probe.probe_ssl("shop.example.com", timeout=1)
    assert result["status"] == "ok"
    assert "shop.example.com" in result["subject"]
    assert result["not_after"].tzinfo is not None
    assert result["not_after"] > now


def test_probe_ssl_reads_expired_cert(monkeypatch):
    """CERT_NONE + binary peercert: an EXPIRED cert still reports its dates."""
    now = datetime.now(UTC)
    der = _self_signed_der(now - timedelta(days=400), now - timedelta(days=30))
    _patch_handshake(monkeypatch, der)
    result = ssl_probe.probe_ssl("shop.example.com", timeout=1)
    assert result["status"] == "ok"
    assert result["not_after"] < now


def test_probe_ssl_connection_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionRefusedError()

    monkeypatch.setattr(ssl_probe.socket, "create_connection", boom)
    result = ssl_probe.probe_ssl("down.example.com", timeout=1)
    assert result == {"status": "error", "error": "ConnectionRefusedError"}


# --- DNS ---------------------------------------------------------------------


def test_lookup_dns_host_and_domain_split(monkeypatch):
    table = {
        ("www.example.com", "A"): ["1.2.3.4"],
        ("www.example.com", "CNAME"): ["example.com."],
        ("example.com", "MX"): ["10 mail.example.com."],
        ("example.com", "TXT"): ['"v=spf1 -all"'],
        ("example.com", "NS"): ["ns1.example.com.", "ns2.example.com."],
    }
    monkeypatch.setattr(
        dns_lookup, "_make_resolver", lambda ip, t: _FakeResolver(table)
    )
    result = dns_lookup.lookup_dns("www.example.com", "example.com", timeout=1)
    assert result["status"] == "ok"
    assert result["records"]["A"] == ["1.2.3.4"]
    assert result["records"]["CNAME"] == ["example.com"]
    assert result["records"]["MX"] == ["10 mail.example.com"]
    assert result["records"]["TXT"] == ["v=spf1 -all"]
    assert result["records"]["NS"] == ["ns1.example.com", "ns2.example.com"]
    assert result["records"]["AAAA"] == []  # NXDOMAIN → empty, not an error


def test_lookup_dns_partial_on_transport_error(monkeypatch):
    table = {
        ("example.com", "A"): ["1.2.3.4"],
        ("example.com", "NS"): dnsres.LifetimeTimeout(),
    }
    monkeypatch.setattr(
        dns_lookup, "_make_resolver", lambda ip, t: _FakeResolver(table)
    )
    result = dns_lookup.lookup_dns("example.com", timeout=1)
    assert result["status"] == "partial"
    assert result["records"]["A"] == ["1.2.3.4"]
    assert "LifetimeTimeout" in result["errors"]


# --- WHOIS -------------------------------------------------------------------

RDAP_PAYLOAD = {
    "handle": "EXAMPLE-COM",
    "events": [
        {"eventAction": "registration", "eventDate": "2020-01-02T03:04:05Z"},
        {"eventAction": "expiration", "eventDate": "2027-01-02T03:04:05Z"},
    ],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": [
                "vcard",
                [["version", {}, "text", "4.0"], ["fn", {}, "text", "GoDaddy.com, LLC"]],
            ],
        }
    ],
}


def test_whois_rdap_ok(monkeypatch):
    monkeypatch.setattr(
        http_pool._POOL, "get", lambda *a, **k: _FakeResp(200, RDAP_PAYLOAD)
    )
    result = whois_lookup.lookup_whois("example.com", timeout=1)
    assert result["status"] == "ok"
    assert result["source"] == "rdap"
    assert result["registrar"] == "GoDaddy.com, LLC"
    assert result["created_at"].year == 2020
    assert result["expires_at"].year == 2027
    assert result["raw"]["handle"] == "EXAMPLE-COM"


def test_whois_falls_back_to_port43(monkeypatch):
    monkeypatch.setattr(http_pool._POOL, "get", lambda *a, **k: _FakeResp(404))
    fake_record = {
        "registrar": "iNET Corp",
        "creation_date": datetime(2019, 5, 1),
        # registries often repeat the field → python-whois returns a list
        "expiration_date": [datetime(2026, 5, 1), datetime(2026, 5, 2)],
    }
    monkeypatch.setattr(whois_lookup.whois43, "whois", lambda d: fake_record)
    result = whois_lookup.lookup_whois("example.com.vn", timeout=1)
    assert result["status"] == "ok"
    assert result["source"] == "whois43"
    assert result["expires_at"] == datetime(2026, 5, 1, tzinfo=UTC)


def test_whois_unsupported_when_both_paths_fail(monkeypatch):
    """Expected for .vn — no RDAP, restricted port-43. Degrades, never raises."""
    monkeypatch.setattr(http_pool._POOL, "get", lambda *a, **k: _FakeResp(404))

    def boom(domain):
        raise ConnectionResetError()

    monkeypatch.setattr(whois_lookup.whois43, "whois", boom)
    result = whois_lookup.lookup_whois("example.vn", timeout=1)
    assert result["status"] == "unsupported"
    assert result["error"] == "ConnectionResetError"


# --- TENTEN provider (.vn WHOIS fallback) ------------------------------------

TENTEN_OK = {
    "code": 1000,
    "msg": "success",
    "cmd": "info.json",
    "data": {
        "domainName": "solarcity.com.vn",
        "registrar": "GMO-Z.com RUNSYSTEM",
        "created_date": "2018-03-15",
        "expiration_date": "2027-03-15",
    },
}
TENTEN_CREDS = {
    "api_key": "k",
    "api_user": "u",
    "base_url": "https://api-reseller.tenten.vn/v1/Domains/",
}


def test_tenten_ok(monkeypatch):
    monkeypatch.setattr(
        http_pool._POOL, "post", lambda *a, **k: _FakeResp(200, TENTEN_OK)
    )
    result = tenten_provider.lookup_tenten("solarcity.com.vn", timeout=1, **TENTEN_CREDS)
    assert result["status"] == "ok"
    assert result["source"] == "tenten"
    assert result["registrar"] == "GMO-Z.com RUNSYSTEM"
    assert result["created_at"].year == 2018
    assert result["expires_at"].year == 2027


def test_tenten_error_code_returns_none(monkeypatch):
    monkeypatch.setattr(
        http_pool._POOL,
        "post",
        lambda *a, **k: _FakeResp(200, {"code": 4001, "msg": "not found"}),
    )
    assert tenten_provider.lookup_tenten("x.vn", timeout=1, **TENTEN_CREDS) is None


def test_tenten_misconfigured_makes_no_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the API without credentials")

    monkeypatch.setattr(http_pool._POOL, "post", boom)
    assert (
        tenten_provider.lookup_tenten(
            "x.vn", timeout=1, api_key="", api_user="", base_url=TENTEN_CREDS["base_url"]
        )
        is None
    )


def test_whois_uses_tenten_when_rdap_missing(monkeypatch):
    """`.vn`: RDAP 404 → the TENTEN provider supplies the authoritative expiry."""
    monkeypatch.setattr(http_pool._POOL, "get", lambda *a, **k: _FakeResp(404))
    monkeypatch.setattr(
        http_pool._POOL, "post", lambda *a, **k: _FakeResp(200, TENTEN_OK)
    )
    # If TENTEN answers, port-43 must not be consulted.
    monkeypatch.setattr(
        whois_lookup.whois43,
        "whois",
        lambda d: (_ for _ in ()).throw(AssertionError("port-43 should be skipped")),
    )
    result = whois_lookup.lookup_whois("solarcity.com.vn", timeout=1, tenten=TENTEN_CREDS)
    assert result["source"] == "tenten"
    assert result["expires_at"].year == 2027


def test_whois_prefers_rdap_over_tenten_for_international(monkeypatch):
    """A solid RDAP answer wins — international lookups never hit the API."""
    monkeypatch.setattr(
        http_pool._POOL, "get", lambda *a, **k: _FakeResp(200, RDAP_PAYLOAD)
    )
    monkeypatch.setattr(
        http_pool._POOL,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("RDAP was ok, skip TENTEN")),
    )
    result = whois_lookup.lookup_whois("example.com", timeout=1, tenten=TENTEN_CREDS)
    assert result["source"] == "rdap"


# --- DNSBL -------------------------------------------------------------------


def test_blacklist_all_clean(monkeypatch):
    monkeypatch.setattr(dnsbl, "_make_resolver", lambda ip, t: _FakeResolver({}))
    result = dnsbl.check_blacklists("example.com", ["1.2.3.4"], timeout=1)
    assert result["verdict"] == "clean"
    assert result["status"] == "ok"
    zen = [r for r in result["results"] if r["list"] == "zen.spamhaus.org"]
    assert zen == [
        {"list": "zen.spamhaus.org", "target": "1.2.3.4", "result": "clean", "detail": ""}
    ]


def test_blacklist_listed(monkeypatch):
    table = {("4.3.2.1.zen.spamhaus.org", "A"): ["127.0.0.2"]}
    monkeypatch.setattr(dnsbl, "_make_resolver", lambda ip, t: _FakeResolver(table))
    result = dnsbl.check_blacklists("example.com", ["1.2.3.4"], timeout=1)
    assert result["verdict"] == "listed"


def test_blacklist_public_resolver_block_is_unknown(monkeypatch):
    """Spamhaus 127.255.255.x codes = resolver refused — NEVER 'listed'."""
    table = {
        ("4.3.2.1.zen.spamhaus.org", "A"): ["127.255.255.254"],
        ("example.com.dbl.spamhaus.org", "A"): ["127.255.255.254"],
    }
    monkeypatch.setattr(dnsbl, "_make_resolver", lambda ip, t: _FakeResolver(table))
    result = dnsbl.check_blacklists("example.com", ["1.2.3.4"], timeout=1)
    assert result["verdict"] == "unknown"
    assert result["status"] == "partial"
    blocked = [r for r in result["results"] if r["detail"] == "ResolverBlocked"]
    assert len(blocked) == 2


def test_blacklist_skips_ipv6(monkeypatch):
    monkeypatch.setattr(dnsbl, "_make_resolver", lambda ip, t: _FakeResolver({}))
    result = dnsbl.check_blacklists("example.com", ["2606:4700::1"], timeout=1)
    assert all(r["list"] != "zen.spamhaus.org" for r in result["results"])


# --- Google index ------------------------------------------------------------


def test_gindex_skipped_without_key():
    result = google_index.check_google_index("example.com", api_key="", cse_id="")
    assert result == {"status": "skipped"}


def test_gindex_ok(monkeypatch):
    payload = {"searchInformation": {"totalResults": "123"}}
    monkeypatch.setattr(
        http_pool._POOL, "get", lambda *a, **k: _FakeResp(200, payload)
    )
    result = google_index.check_google_index(
        "example.com", api_key="k", cse_id="c", timeout=1
    )
    assert result == {"status": "ok", "indexed": True, "total_results": 123}


def test_gindex_not_indexed(monkeypatch):
    payload = {"searchInformation": {"totalResults": "0"}}
    monkeypatch.setattr(
        http_pool._POOL, "get", lambda *a, **k: _FakeResp(200, payload)
    )
    result = google_index.check_google_index(
        "example.com", api_key="k", cse_id="c", timeout=1
    )
    assert result["indexed"] is False


def test_gindex_quota_error(monkeypatch):
    monkeypatch.setattr(http_pool._POOL, "get", lambda *a, **k: _FakeResp(429))
    result = google_index.check_google_index(
        "example.com", api_key="k", cse_id="c", timeout=1
    )
    assert result["status"] == "error"
