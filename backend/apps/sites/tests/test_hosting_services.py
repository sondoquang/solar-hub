import httpx
import pytest

from apps.integrations.woocommerce import WooClient
from apps.sites import services
from apps.sites.models import Hosting, Site

from .factories import HostingFactory, SiteFactory


@pytest.mark.django_db
def test_check_hosting_only_checks_its_own_sites(monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    h1, h2 = HostingFactory(), HostingFactory()
    in_group = [SiteFactory(hosting=h1), SiteFactory(hosting=h1)]
    other = SiteFactory(hosting=h2)
    orphan = SiteFactory(hosting=None)

    results = services.check_hosting(h1.id)

    assert {r["id"] for r in results} == {s.id for s in in_group}
    for site in in_group:
        site.refresh_from_db()
        assert site.status == Site.Status.UP
    # Sites outside the hosting are untouched.
    other.refresh_from_db()
    orphan.refresh_from_db()
    assert other.status == Site.Status.UNKNOWN
    assert orphan.status == Site.Status.UNKNOWN


@pytest.mark.django_db
def test_check_hosting_none_checks_orphan_sites(monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    orphan = SiteFactory(hosting=None)
    grouped = SiteFactory(hosting=HostingFactory())

    results = services.check_hosting(None)

    assert [r["id"] for r in results] == [orphan.id]
    grouped.refresh_from_db()
    assert grouped.status == Site.Status.UNKNOWN


@pytest.mark.django_db
def test_check_hosting_marks_down_on_error(monkeypatch):
    def boom(self):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(WooClient, "system_status", boom)
    hosting = HostingFactory()
    site = SiteFactory(hosting=hosting)

    services.check_hosting(hosting.id)

    site.refresh_from_db()
    assert site.status == Site.Status.DOWN


@pytest.mark.django_db
def test_check_hosting_respects_concurrency(monkeypatch):
    """With check_concurrency=1, no two checks overlap. We assert the executor
    never runs more workers than the configured concurrency."""
    import threading

    hosting = HostingFactory(check_concurrency=1)
    for _ in range(4):
        SiteFactory(hosting=hosting)

    active = 0
    peak = 0
    lock = threading.Lock()

    def tracking_status(self):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            return {"environment": {}}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(WooClient, "system_status", tracking_status)
    services.check_hosting(hosting.id)
    assert peak == 1


@pytest.mark.django_db
def test_delete_hosting_soft_deletes_and_keeps_sites():
    hosting = HostingFactory()
    site = SiteFactory(hosting=hosting)

    services.delete_hosting(hosting)

    hosting.refresh_from_db()
    site.refresh_from_db()
    assert hosting.is_deleted is True
    assert hosting.deleted_at is not None
    # The site keeps its link to the (now hidden) hosting.
    assert site.hosting_id == hosting.id
