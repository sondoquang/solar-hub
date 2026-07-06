from datetime import timedelta

import pytest
from django.utils import timezone

from apps.domains import tasks
from apps.sites.tests.factories import SiteFactory

from .factories import DomainInfoFactory


@pytest.mark.django_db
def test_detail_404_before_first_check(client):
    site = SiteFactory()
    resp = client.get(f"/api/domain-info/{site.id}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_detail_returns_snapshot_with_countdowns(client):
    site = SiteFactory(name="Solar VN")
    DomainInfoFactory(
        site=site,
        domain="solar.vn",
        whois_expires_at=timezone.now() + timedelta(days=45),
        ssl_not_after=timezone.now() + timedelta(days=10),
    )
    resp = client.get(f"/api/domain-info/{site.id}/")
    assert resp.status_code == 200
    assert resp.data["site_name"] == "Solar VN"
    assert resp.data["domain"] == "solar.vn"
    assert 43 <= resp.data["whois_days_remaining"] <= 45
    assert 8 <= resp.data["ssl_days_remaining"] <= 10
    assert resp.data["is_pending"] is False


@pytest.mark.django_db
def test_list_excludes_deleted_sites_and_orders_by_expiry(client):
    soon = DomainInfoFactory(ssl_not_after=timezone.now() + timedelta(days=3))
    later = DomainInfoFactory(ssl_not_after=timezone.now() + timedelta(days=300))
    deleted = DomainInfoFactory()
    deleted.site.is_deleted = True
    deleted.site.save(update_fields=["is_deleted"])

    resp = client.get("/api/domain-info/", {"ordering": "ssl_not_after"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data["results"]]
    assert ids == [soon.id, later.id]


@pytest.mark.django_db
def test_refresh_enqueues_on_interactive_queue(client, monkeypatch):
    captured = {}

    def fake_apply_async(*args, **kwargs):
        captured["args"] = kwargs.get("args") or (args[0] if args else None)
        captured["queue"] = kwargs.get("queue")

    monkeypatch.setattr(tasks.refresh_site_domain_info, "apply_async", fake_apply_async)
    site = SiteFactory()
    resp = client.post(f"/api/domain-info/{site.id}/refresh/", {}, format="json")
    assert resp.status_code == 202
    assert resp.data["is_pending"] is True
    assert captured["args"] == [site.id, None]
    assert captured["queue"] == "interactive"


@pytest.mark.django_db
def test_refresh_validates_check_names(client, monkeypatch):
    monkeypatch.setattr(
        tasks.refresh_site_domain_info, "apply_async", lambda *a, **k: None
    )
    site = SiteFactory()
    resp = client.post(
        f"/api/domain-info/{site.id}/refresh/", {"checks": ["ssl", "bogus"]},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_refresh_404_for_deleted_site(client):
    site = SiteFactory(is_deleted=True)
    resp = client.post(f"/api/domain-info/{site.id}/refresh/", {}, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_refresh_all_forces_dispatcher_on_interactive(client, monkeypatch):
    captured = {}

    def fake_apply_async(*args, **kwargs):
        captured["kwargs"] = kwargs.get("kwargs")
        captured["queue"] = kwargs.get("queue")

    monkeypatch.setattr(tasks.refresh_all_domain_info, "apply_async", fake_apply_async)
    resp = client.post("/api/domain-info/refresh-all/", {}, format="json")
    assert resp.status_code == 202
    assert captured["kwargs"] == {"force": True, "queue": "interactive"}
    assert captured["queue"] == "interactive"


@pytest.mark.django_db
def test_requires_auth():
    from rest_framework.test import APIClient

    resp = APIClient().get("/api/domain-info/")
    assert resp.status_code == 401
