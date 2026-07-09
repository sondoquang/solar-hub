"""Domain-info orchestration — Celery-only entry points.

``refresh_domain_info`` runs the requested lookups from ``apps/domains/checks``
(pure functions that never raise) and persists the one snapshot row per site.
The lookups are slow network I/O, so nothing here may be called from the DRF
request cycle; views only ``mark_pending`` + enqueue.
"""

import logging
from urllib.parse import urlsplit

import tldextract
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.core.logging_utils import log_event

from .checks import dns_lookup, dnsbl, google_index, ssl_probe, whois_lookup
from .models import DomainInfo

logger = logging.getLogger(__name__)

ALL_CHECKS = ("whois", "dns", "ssl", "blacklist", "gindex")

# Bundled public-suffix snapshot only — extraction must never do network I/O
# inside a worker thread.
_extract = tldextract.TLDExtract(suffix_list_urls=())

# Several Site rows often share one registrable domain (Sapo storefronts, dev
# subdomains); within a fan-out run the WHOIS answer is reused via this cache.
_WHOIS_CACHE_SECONDS = 600


# tldextract renamed ``registered_domain`` → ``top_domain_under_public_suffix``
# in 5.3 (old name deprecated). Pick the attribute name once, by version, so we
# never touch the deprecated property when the new one exists.
_REGISTRABLE_ATTR = (
    "top_domain_under_public_suffix"
    if hasattr(_extract("example.com"), "top_domain_under_public_suffix")
    else "registered_domain"
)


def extract_domain(base_url: str) -> tuple[str, str]:
    """base_url → (host, registrable domain). IPs/localhost fall back to host."""
    host = (urlsplit(base_url).hostname or base_url).strip().lower().rstrip(".")
    registrable = getattr(_extract(host), _REGISTRABLE_ATTR)
    return host, (registrable or host)


def mark_pending(site, checks=None) -> DomainInfo:
    """Flag the requested checks PENDING before enqueueing a manual refresh, so
    the frontend can poll ``is_pending`` until the worker finishes."""
    requested = set(checks or ALL_CHECKS) & set(ALL_CHECKS)
    host, domain = extract_domain(site.base_url)
    info, _ = DomainInfo.objects.get_or_create(
        site=site, defaults={"host": host, "domain": domain}
    )
    fields = []
    for check in requested:
        setattr(info, f"{check}_status", DomainInfo.CheckStatus.PENDING)
        fields.append(f"{check}_status")
    info.save(update_fields=fields + ["updated_at"])
    return info


def refresh_domain_info(site, checks=None, *, force=False) -> DomainInfo:
    """Run the requested checks and persist the snapshot. ``force=True`` (manual
    refresh) bypasses the Google-index quota cadence."""
    requested = set(checks or ALL_CHECKS) & set(ALL_CHECKS)
    host, domain = extract_domain(site.base_url)
    info, _ = DomainInfo.objects.get_or_create(
        site=site, defaults={"host": host, "domain": domain}
    )
    lock = f"domain-refresh:{site.id}"
    if not cache.add(lock, 1, timeout=120):
        return info  # another worker is already refreshing this site
    log_event(
        logger, logging.INFO, "refresh_domain_info start",
        site_id=site.id, checks=len(requested),
    )
    try:
        info = _run_checks(info, host, domain, requested, force)
    finally:
        cache.delete(lock)
    # Checks never raise; any failure is captured per-check into last_error.
    n_errors = len(info.last_error.split("; ")) if info.last_error else 0
    log_event(
        logger, logging.WARNING if n_errors else logging.INFO, "refresh_domain_info done",
        site_id=site.id, errors=n_errors or None,
    )
    return info


def _run_checks(info, host, domain, requested, force) -> DomainInfo:
    info.host, info.domain = host, domain
    now = timezone.now()
    timeout = settings.DOMAIN_LOOKUP_TIMEOUT_SECONDS
    resolver_ip = settings.DOMAIN_DNS_RESOLVER or None
    errors: list[str] = []

    if "whois" in requested:
        result = _cached_whois(domain, timeout)
        info.whois_status = result["status"]
        info.whois_registrar = result.get("registrar", "")
        info.whois_created_at = result.get("created_at")
        info.whois_expires_at = result.get("expires_at")
        info.whois_source = result.get("source", "")
        info.whois_raw = result.get("raw", {})
        info.whois_checked_at = now
        if result.get("error"):
            errors.append(f"whois:{result['error']}")

    dns_result = None
    if "dns" in requested or "blacklist" in requested:
        # The blacklist check needs the A records — one lookup feeds both.
        dns_result = dns_lookup.lookup_dns(
            host, domain, resolver_ip=resolver_ip, timeout=timeout
        )
    if "dns" in requested:
        info.dns_status = dns_result["status"]
        info.dns_records = dns_result["records"]
        info.dns_checked_at = now
        errors.extend(f"dns:{e}" for e in dns_result.get("errors", [])[:2])

    if "ssl" in requested:
        result = ssl_probe.probe_ssl(host, timeout=timeout)
        info.ssl_status = result["status"]
        info.ssl_issuer = result.get("issuer", "")
        info.ssl_subject = result.get("subject", "")
        info.ssl_not_before = result.get("not_before")
        info.ssl_not_after = result.get("not_after")
        info.ssl_checked_at = now
        if result.get("error"):
            errors.append(f"ssl:{result['error']}")

    if "blacklist" in requested:
        ips = dns_result["records"].get("A", [])
        result = dnsbl.check_blacklists(
            domain, ips, resolver_ip=resolver_ip, timeout=timeout
        )
        info.blacklist_status = result["status"]
        info.blacklist_verdict = result["verdict"]
        info.blacklist_results = result["results"]
        info.blacklist_checked_at = now

    if "gindex" in requested:
        if _gindex_due(info, force):
            result = google_index.check_google_index(
                domain,
                api_key=settings.GOOGLE_CSE_API_KEY,
                cse_id=settings.GOOGLE_CSE_CX,
                timeout=timeout,
            )
            info.gindex_status = result["status"]
            info.gindex_indexed = result.get("indexed")
            info.gindex_total_results = result.get("total_results")
            info.gindex_checked_at = now
            if result.get("error"):
                errors.append(f"gindex:{result['error']}")
        elif info.gindex_status == DomainInfo.CheckStatus.PENDING:
            # Marked pending but the quota cadence says "not yet" — un-stick it
            # so the frontend stops polling.
            info.gindex_status = DomainInfo.CheckStatus.SKIPPED

    info.last_error = "; ".join(errors)[:255]
    info.last_refreshed_at = now
    info.save()
    return info


def _gindex_due(info, force) -> bool:
    if force:
        return True
    if not settings.GOOGLE_CSE_API_KEY:
        return True  # cheap no-op: records "skipped" so the UI shows why
    if info.gindex_checked_at is None:
        return True
    age = (timezone.now() - info.gindex_checked_at).total_seconds()
    return age >= settings.DOMAIN_GINDEX_INTERVAL_SECONDS


def _tenten_config() -> dict | None:
    """TENTEN reseller creds for the WHOIS ``.vn`` fallback, or None when unset
    (then WHOIS uses only RDAP/port-43 and ``.vn`` stays "unsupported")."""
    if settings.TENTEN_API_KEY and settings.TENTEN_API_USER:
        return {
            "api_key": settings.TENTEN_API_KEY,
            "api_user": settings.TENTEN_API_USER,
            "base_url": settings.TENTEN_API_BASE_URL,
        }
    return None


def _cached_whois(domain, timeout) -> dict:
    key = f"domain-whois:{domain}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = whois_lookup.lookup_whois(
        domain, timeout=timeout, tenten=_tenten_config()
    )
    cache.set(key, result, timeout=_WHOIS_CACHE_SECONDS)
    return result
