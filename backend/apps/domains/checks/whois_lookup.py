"""WHOIS lookup — RDAP first (structured JSON over HTTPS), port-43 fallback.

RDAP: ``GET https://rdap.org/domain/{domain}`` — the bootstrap redirects to the
authoritative registry server (the shared pool follows redirects). A 404 or a
TLD without RDAP falls back to classic whois (python-whois). ``.vn`` has
neither public RDAP nor an open whois server, so both paths failing is EXPECTED
there → status "unsupported" (UI: "Chưa hỗ trợ"), never an exception.
"""

from datetime import UTC, datetime

import whois as whois43

from . import http_pool

RDAP_URL = "https://rdap.org/domain/{domain}"


def _parse_iso(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _first(value):
    # python-whois returns a list when the registry repeats a field.
    if isinstance(value, list | tuple):
        return value[0] if value else None
    return value


def _aware(value):
    value = _first(value)
    if isinstance(value, str):
        return _parse_iso(value)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _status_for(registrar, created, expires) -> str:
    if expires and registrar:
        return "ok"
    if registrar or created or expires:
        return "partial"
    return "unsupported"


def _rdap(domain: str, timeout: float):
    """Parsed RDAP result, or None → let the port-43 fallback try."""
    try:
        resp = http_pool._POOL.get(
            RDAP_URL.format(domain=domain),
            timeout=timeout,
            headers={"Accept": "application/rdap+json"},
        )
        if resp.status_code == 404:  # TLD/domain not in any RDAP registry
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    created = expires = None
    for event in data.get("events") or []:
        action = event.get("eventAction")
        if action == "registration":
            created = _parse_iso(event.get("eventDate"))
        elif action == "expiration":
            expires = _parse_iso(event.get("eventDate"))

    registrar = ""
    for entity in data.get("entities") or []:
        if "registrar" not in (entity.get("roles") or []):
            continue
        vcard = entity.get("vcardArray") or [None, []]
        for entry in vcard[1]:
            if entry and entry[0] == "fn" and len(entry) > 3 and entry[3]:
                registrar = str(entry[3])[:255]
                break
        if registrar:
            break

    if not (registrar or created or expires):
        return None  # answered but nothing usable
    raw = {k: data.get(k) for k in ("handle", "status", "events") if k in data}
    return {
        "status": _status_for(registrar, created, expires),
        "registrar": registrar,
        "created_at": created,
        "expires_at": expires,
        "source": "rdap",
        "raw": raw,
    }


def _whois_port43(domain: str) -> dict:
    try:
        record = whois43.whois(domain)
    except Exception as exc:
        return {
            "status": "unsupported",
            "error": type(exc).__name__,
            "source": "whois43",
            "raw": {},
        }
    registrar = str(_first(record.get("registrar")) or "")[:255]
    created = _aware(record.get("creation_date"))
    expires = _aware(record.get("expiration_date"))
    raw = {
        k: str(record.get(k))[:500]
        for k in ("registrar", "creation_date", "expiration_date", "status", "name_servers")
        if record.get(k)
    }
    return {
        "status": _status_for(registrar, created, expires),
        "registrar": registrar,
        "created_at": created,
        "expires_at": expires,
        "source": "whois43",
        "raw": raw,
    }


def lookup_whois(domain: str, *, timeout: float = 10.0, tenten: dict | None = None) -> dict:
    """RDAP → TENTEN provider (if configured) → port-43 whois.

    RDAP handles international TLDs for free; ``tenten`` (a ``{api_key, api_user,
    base_url}`` dict from settings, or ``None``) fills ``.vn`` and any domain the
    company registers at TENTEN, which RDAP/port-43 can't reach; port-43 is the
    last resort. We only reach for the provider when RDAP didn't already return a
    solid ("ok") answer, so most international lookups never touch TENTEN.
    """
    result = _rdap(domain, timeout)
    if result is not None and result.get("status") == "ok":
        return result
    if tenten:
        # Lazy import avoids a circular import with tenten_provider (which pulls
        # _parse_iso from this module at its top level).
        from . import tenten_provider

        provider = tenten_provider.lookup_tenten(domain, timeout=timeout, **tenten)
        if provider is not None:
            return provider
    if result is not None:
        return result  # keep RDAP's partial answer if the provider didn't help
    return _whois_port43(domain)
