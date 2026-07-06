from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.domains import services
from apps.domains.models import DomainInfo
from apps.sites.tests.factories import SiteFactory

from .factories import DomainInfoFactory

OK_WHOIS = {
    "status": "ok",
    "registrar": "GoDaddy.com, LLC",
    "created_at": datetime(2020, 1, 2, tzinfo=UTC),
    "expires_at": datetime(2027, 1, 2, tzinfo=UTC),
    "source": "rdap",
    "raw": {"handle": "X"},
}
OK_DNS = {"status": "ok", "records": {"A": ["1.2.3.4"], "MX": []}, "errors": []}
OK_SSL = {
    "status": "ok",
    "issuer": "CN=R11,O=Let's Encrypt",
    "subject": "CN=shop.example.com",
    "not_before": datetime(2026, 5, 1, tzinfo=UTC),
    "not_after": datetime(2026, 8, 1, tzinfo=UTC),
}
OK_BLACKLIST = {"status": "ok", "verdict": "clean", "results": []}


def _stub_checks(monkeypatch, *, whois=OK_WHOIS, dns=OK_DNS, ssl_result=OK_SSL,
                 blacklist=OK_BLACKLIST, gindex=None):
    monkeypatch.setattr(
        services.whois_lookup,
        "lookup_whois",
        lambda d, timeout, tenten=None: dict(whois),
    )
    monkeypatch.setattr(
        services.dns_lookup, "lookup_dns", lambda *a, **k: dict(dns)
    )
    monkeypatch.setattr(
        services.ssl_probe, "probe_ssl", lambda *a, **k: dict(ssl_result)
    )
    monkeypatch.setattr(
        services.dnsbl, "check_blacklists", lambda *a, **k: dict(blacklist)
    )
    monkeypatch.setattr(
        services.google_index,
        "check_google_index",
        lambda *a, **k: dict(gindex or {"status": "skipped"}),
    )


def test_extract_domain_registrable_vs_host():
    assert services.extract_domain("https://shop.example.com.vn/wp-json") == (
        "shop.example.com.vn",
        "example.com.vn",
    )
    assert services.extract_domain("https://example.com") == (
        "example.com",
        "example.com",
    )
    # IPs / bare hosts have no registrable domain → fall back to the host
    assert services.extract_domain("http://192.168.1.10:8080") == (
        "192.168.1.10",
        "192.168.1.10",
    )


@pytest.mark.django_db
def test_refresh_persists_full_snapshot(monkeypatch):
    _stub_checks(monkeypatch)
    site = SiteFactory(base_url="https://shop.example.com")
    info = services.refresh_domain_info(site)

    assert info.host == "shop.example.com"
    assert info.domain == "example.com"
    assert info.whois_status == "ok"
    assert info.whois_registrar == "GoDaddy.com, LLC"
    assert info.whois_expires_at.year == 2027
    assert info.dns_records["A"] == ["1.2.3.4"]
    assert info.ssl_not_after.year == 2026
    assert info.blacklist_verdict == "clean"
    assert info.gindex_status == "skipped"
    assert info.last_refreshed_at is not None
    assert info.last_error == ""
    assert not info.is_pending

    # Refreshing again updates the SAME row (snapshot, not history).
    services.refresh_domain_info(site)
    assert DomainInfo.objects.filter(site=site).count() == 1


@pytest.mark.django_db
def test_partial_failure_degrades_only_that_section(monkeypatch):
    _stub_checks(
        monkeypatch,
        whois={"status": "unsupported", "error": "ConnectionResetError",
               "source": "whois43", "raw": {}},
        ssl_result={"status": "error", "error": "TimeoutError"},
    )
    site = SiteFactory(base_url="https://shop.example.vn")
    info = services.refresh_domain_info(site)

    assert info.whois_status == "unsupported"  # .vn — expected, not an error
    assert info.ssl_status == "error"
    assert info.dns_status == "ok"  # unaffected by the failing sections
    assert info.blacklist_verdict == "clean"
    assert "whois:ConnectionResetError" in info.last_error
    assert "ssl:TimeoutError" in info.last_error


@pytest.mark.django_db
def test_refresh_subset_leaves_other_sections_untouched(monkeypatch):
    _stub_checks(monkeypatch)
    info = DomainInfoFactory(whois_registrar="Old registrar")
    services.refresh_domain_info(info.site, checks=["ssl"])
    info.refresh_from_db()
    assert info.ssl_status == "ok"
    assert info.whois_registrar == "Old registrar"
    assert info.whois_checked_at is None


@pytest.mark.django_db
def test_mark_pending_subset(monkeypatch):
    info = DomainInfoFactory()
    assert not info.is_pending
    services.mark_pending(info.site, ["ssl", "dns"])
    info.refresh_from_db()
    assert info.ssl_status == DomainInfo.CheckStatus.PENDING
    assert info.dns_status == DomainInfo.CheckStatus.PENDING
    assert info.whois_status == DomainInfo.CheckStatus.OK
    assert info.is_pending


@pytest.mark.django_db
def test_gindex_cadence_skips_recent_check(monkeypatch, settings):
    settings.GOOGLE_CSE_API_KEY = "key"
    settings.GOOGLE_CSE_CX = "cx"
    calls = []

    def counting_gindex(*a, **k):
        calls.append(1)
        return {"status": "ok", "indexed": True, "total_results": 5}

    _stub_checks(monkeypatch)
    monkeypatch.setattr(services.google_index, "check_google_index", counting_gindex)

    info = DomainInfoFactory(
        gindex_status="ok", gindex_checked_at=timezone.now() - timedelta(hours=1)
    )
    # Periodic refresh: checked 1h ago < 7-day cadence → quota-guarded, no call.
    services.refresh_domain_info(info.site)
    assert calls == []
    # Manual refresh (force): the user asked explicitly → bypasses the cadence.
    services.refresh_domain_info(info.site, force=True)
    assert calls == [1]


@pytest.mark.django_db
def test_whois_memo_shared_across_sites_of_one_domain(monkeypatch):
    _stub_checks(monkeypatch)
    calls = []

    def counting_whois(domain, timeout, tenten=None):
        calls.append(domain)
        return dict(OK_WHOIS)

    monkeypatch.setattr(services.whois_lookup, "lookup_whois", counting_whois)
    site_a = SiteFactory(base_url="https://a.example.org")
    site_b = SiteFactory(base_url="https://b.example.org")
    services.refresh_domain_info(site_a, checks=["whois"])
    services.refresh_domain_info(site_b, checks=["whois"])
    assert calls == ["example.org"]  # second site reused the memoized answer
