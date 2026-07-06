"""WHOIS via the TENTEN (GMO) reseller API — the ``.vn`` fallback.

VNNIC publishes no public RDAP and blocks port-43 whois from outside Vietnam,
so ``.vn`` domains can't be resolved by the generic RDAP/whois path. TENTEN is
an official VNNIC-connected registrar; its reseller API returns structured
registrar + expiry for domains under the account.

Config-gated: without an api_key/api_user the service layer passes
``tenten=None`` and this is never called. Returns ``None`` on any miss so the
caller keeps whatever the RDAP/whois path produced. **Never raises.**

Contract (id.tenten.vn/document_api): ``POST {base_url}`` form-data
``{cmd, api_key, api_user, domainName}``; ``cmd=info.json`` → structured
``data`` with created/expiration dates; envelope ``{code, msg, data, ...}`` with
``code==1000`` on success. The exact field names inside ``data`` are matched
defensively (a few likely spellings, one nested level) and must be confirmed
against a live key — see the plan's verify section.
"""

from .whois_lookup import _parse_iso

# Candidate field names inside the ``data`` object (confirm against a live key).
_EXPIRE_KEYS = (
    "expiration_date", "expired_date", "expire_date", "exp_date",
    "date_expired", "expiry_date", "expire",
)
_CREATE_KEYS = (
    "created_date", "creation_date", "registered_date", "date_created",
    "registration_date", "created",
)
_REGISTRAR_KEYS = ("registrar", "registrar_name", "sponsoring_registrar", "sponsor")


def _find(data: dict, keys):
    """First present, non-empty value among ``keys`` — top level, then one
    nested dict level (some APIs wrap the record under ``data.domain`` etc.)."""
    for k in keys:
        if data.get(k):
            return data[k]
    for sub in data.values():
        if isinstance(sub, dict):
            for k in keys:
                if sub.get(k):
                    return sub[k]
    return None


def lookup_tenten(
    domain: str, *, api_key: str, api_user: str, base_url: str, timeout: float = 10.0
) -> dict | None:
    if not (api_key and api_user and base_url):
        return None
    # Local import keeps the module importable without a configured pool in
    # tests and avoids a hard dep at import time.
    from . import http_pool

    try:
        resp = http_pool._POOL.post(
            base_url,
            data={
                "cmd": "info.json",
                "api_key": api_key,
                "api_user": api_user,
                "domainName": domain,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    # code 1000 = success; anything else (4001 = error, not-found, …) → let the
    # caller fall through to its existing result.
    if str(payload.get("code")) != "1000":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    expires = _parse_iso(_find(data, _EXPIRE_KEYS))
    created = _parse_iso(_find(data, _CREATE_KEYS))
    if not (expires or created):
        return None  # answered but nothing usable
    registrar = str(_find(data, _REGISTRAR_KEYS) or "TENTEN (GMO)")[:255]
    raw = {
        k: data[k]
        for k in (*_EXPIRE_KEYS, *_CREATE_KEYS, *_REGISTRAR_KEYS)
        if k in data
    }
    return {
        "status": "ok" if expires else "partial",
        "registrar": registrar,
        "created_at": created,
        "expires_at": expires,
        "source": "tenten",
        "raw": raw,
    }
