from datetime import timedelta

import pytest
from django.utils import timezone

from apps.domains import services, tasks
from apps.sites.tests.factories import SiteFactory

from .factories import DomainInfoFactory


def _capture_batches(monkeypatch):
    batches = []

    def fake_apply_async(*args, **kwargs):
        batches.append({"ids": kwargs["args"][0], "queue": kwargs.get("queue")})

    monkeypatch.setattr(tasks.refresh_domain_batch, "apply_async", fake_apply_async)
    return batches


@pytest.mark.django_db
def test_dispatcher_selects_only_stale_sites(monkeypatch):
    batches = _capture_batches(monkeypatch)
    fresh = DomainInfoFactory(last_refreshed_at=timezone.now())
    stale = DomainInfoFactory(last_refreshed_at=timezone.now() - timedelta(days=2))
    never = SiteFactory()  # no snapshot yet
    deleted = SiteFactory(is_deleted=True)

    result = tasks.refresh_all_domain_info()
    dispatched = {i for b in batches for i in b["ids"]}
    assert dispatched == {stale.site_id, never.id}
    assert fresh.site_id not in dispatched
    assert deleted.id not in dispatched
    assert result == {"sites": 2, "batches": 1}


@pytest.mark.django_db
def test_dispatcher_force_includes_fresh_sites_and_chunks(monkeypatch, settings):
    settings.DOMAIN_INFO_BATCH_SIZE = 2
    batches = _capture_batches(monkeypatch)
    for _ in range(3):
        DomainInfoFactory(last_refreshed_at=timezone.now())

    result = tasks.refresh_all_domain_info(force=True, queue="interactive")
    assert result == {"sites": 3, "batches": 2}
    assert [len(b["ids"]) for b in batches] == [2, 1]
    assert all(b["queue"] == "interactive" for b in batches)


@pytest.mark.django_db
def test_batch_refreshes_each_site(monkeypatch):
    refreshed = []
    monkeypatch.setattr(
        services,
        "refresh_domain_info",
        lambda site, checks=None, force=False: refreshed.append(site.id),
    )
    sites = [SiteFactory() for _ in range(3)]
    result = tasks.refresh_domain_batch([s.id for s in sites])
    assert result == {"refreshed": 3}
    assert sorted(refreshed) == sorted(s.id for s in sites)


@pytest.mark.django_db
def test_single_site_task_skips_deleted(monkeypatch):
    monkeypatch.setattr(
        services, "refresh_domain_info", lambda *a, **k: pytest.fail("must not run")
    )
    site = SiteFactory(is_deleted=True)
    assert tasks.refresh_site_domain_info(site.id) == {"refreshed": 0}
