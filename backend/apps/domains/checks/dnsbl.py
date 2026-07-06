"""DNSBL blacklist checks (Spamhaus ZEN/DBL, SURBL).

Per-query semantics: NXDOMAIN = clean; an answer inside 127.0.0.0/8 = listed —
EXCEPT the Spamhaus 127.255.255.0/24 error codes (public/open resolver refused,
query limit) which mean "no answer available" → unknown. Timeouts/SERVFAIL →
unknown. UNKNOWN must never surface as LISTED: on the default Docker/public
resolver Spamhaus typically refuses queries, and ``DOMAIN_DNS_RESOLVER`` exists
to point at a resolver that is allowed to ask.
"""

import dns.resolver

from .dns_lookup import _make_resolver

IP_LISTS = ("zen.spamhaus.org",)
DOMAIN_LISTS = ("dbl.spamhaus.org", "multi.surbl.org")
MAX_IPS = 3  # bound the fan-out for round-robin A records


def _query(resolver, qname: str) -> tuple[str, str]:
    try:
        answer = resolver.resolve(qname, "A")
    except dns.resolver.NXDOMAIN:
        return "clean", ""
    except Exception as exc:
        return "unknown", type(exc).__name__
    codes = sorted(r.to_text() for r in answer)
    if any(c.startswith("127.255.255.") for c in codes):
        return "unknown", "ResolverBlocked"
    if any(c.startswith("127.") for c in codes):
        return "listed", ", ".join(codes)
    # Anything outside 127/8 is a mangled answer (captive/forwarding DNS).
    return "unknown", ", ".join(codes)


def check_blacklists(
    domain: str,
    ips,
    *,
    resolver_ip: str | None = None,
    timeout: float = 5.0,
) -> dict:
    resolver = _make_resolver(resolver_ip, timeout)
    results = []
    for ip in list(ips)[:MAX_IPS]:
        if ":" in ip:
            continue  # reversal below is IPv4-only
        reversed_ip = ".".join(reversed(ip.split(".")))
        for bl in IP_LISTS:
            verdict, detail = _query(resolver, f"{reversed_ip}.{bl}")
            results.append({"list": bl, "target": ip, "result": verdict, "detail": detail})
    for bl in DOMAIN_LISTS:
        verdict, detail = _query(resolver, f"{domain}.{bl}")
        results.append({"list": bl, "target": domain, "result": verdict, "detail": detail})

    verdicts = {r["result"] for r in results}
    if "listed" in verdicts:
        overall = "listed"
    elif verdicts == {"clean"}:
        overall = "clean"
    else:
        overall = "unknown"
    status = "ok" if "unknown" not in verdicts else "partial"
    return {"status": status, "verdict": overall, "results": results}
