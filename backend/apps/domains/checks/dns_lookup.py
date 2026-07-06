"""DNS record lookup via dnspython.

A/AAAA/CNAME are asked on the full ``host`` (that is what the browser resolves);
NS/MX/TXT on the registrable ``domain`` (where those records actually live —
asking a ``www.`` host for NS/MX would mostly return empty). NoAnswer/NXDOMAIN
per type is a normal empty result; only transport failures (timeout, SERVFAIL)
count as errors.

Pure functions, no model imports, never raises.
"""

import dns.resolver

HOST_TYPES = ("A", "AAAA", "CNAME")
DOMAIN_TYPES = ("NS", "MX", "TXT")


def _make_resolver(resolver_ip: str | None, timeout: float) -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver()
    if resolver_ip:
        resolver.nameservers = [resolver_ip]
    resolver.timeout = timeout
    resolver.lifetime = timeout
    return resolver


def _rdata_text(rdata, rtype: str) -> str:
    text = rdata.to_text().rstrip(".")
    if rtype == "TXT":
        # to_text() wraps each string in quotes; join to one readable value.
        text = text.replace('" "', "").strip('"')
    return text


def lookup_dns(
    host: str,
    domain: str | None = None,
    *,
    resolver_ip: str | None = None,
    timeout: float = 10.0,
) -> dict:
    domain = domain or host
    resolver = _make_resolver(resolver_ip, timeout)
    records: dict[str, list[str]] = {}
    errors: list[str] = []

    for name, rtypes in ((host, HOST_TYPES), (domain, DOMAIN_TYPES)):
        for rtype in rtypes:
            try:
                answer = resolver.resolve(name, rtype)
                records[rtype] = sorted(_rdata_text(r, rtype) for r in answer)
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                records[rtype] = []
            except Exception as exc:
                records[rtype] = []
                errors.append(type(exc).__name__)

    if not errors:
        status = "ok"
    elif any(records.values()):
        status = "partial"
    else:
        status = "error"
    return {"status": status, "records": records, "errors": errors}
