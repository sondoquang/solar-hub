import pytest

from apps.sync import tasks


@pytest.mark.django_db
def test_poll_all_orders_chunks_into_batches(monkeypatch):
    """All non-deleted sites are split into batches of ORDER_POLL_BATCH_SIZE."""
    from apps.sites.tests.factories import SiteFactory

    sites = [SiteFactory() for _ in range(5)]
    ids = sorted(s.id for s in sites)

    monkeypatch.setattr(tasks, "_batch_size", lambda: 2)
    dispatched = []

    def _delay(chunk, status, date_from, date_to, run_id=None, triggered_by_id=None):
        dispatched.append((chunk, status))

    monkeypatch.setattr(tasks.poll_sites_batch_task, "delay", _delay)

    result = tasks.poll_all_orders()
    assert result == {"status": "processing", "sites": 5, "batches": 3, "run_id": None}
    # 5 sites, size 2 → [2, 2, 1]; every id dispatched exactly once.
    assert [len(c) for c, _ in dispatched] == [2, 2, 1]
    assert sorted(i for c, _ in dispatched for i in c) == ids
    assert all(s == "processing" for _, s in dispatched)


@pytest.mark.django_db
def test_poll_all_orders_filters_to_selected_sites(monkeypatch):
    from apps.sites.tests.factories import SiteFactory

    keep = SiteFactory()
    SiteFactory()  # excluded

    monkeypatch.setattr(tasks, "_batch_size", lambda: 8)
    dispatched = []

    def _delay(chunk, status, date_from, date_to, run_id=None, triggered_by_id=None):
        dispatched.append((chunk, status))

    monkeypatch.setattr(tasks.poll_sites_batch_task, "delay", _delay)

    result = tasks.poll_all_orders(status="completed", site_ids=[keep.id])
    assert result == {"status": "completed", "sites": 1, "batches": 1, "run_id": None}
    assert dispatched == [([keep.id], "completed")]


@pytest.mark.django_db
def test_poll_all_orders_platform_scopes_to_woocommerce(monkeypatch, settings):
    """``platform="woocommerce"`` dispatches only Woo sites, even with Sapo on."""
    from apps.sites.models import Site
    from apps.sites.tests.factories import SiteFactory

    settings.SAPO_ORDER_POLL_ENABLED = True
    woo = SiteFactory()
    SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")

    monkeypatch.setattr(tasks, "_batch_size", lambda: 8)
    dispatched = []

    def _delay(chunk, status, date_from, date_to, run_id=None, triggered_by_id=None):
        dispatched.append(chunk)

    monkeypatch.setattr(tasks.poll_sites_batch_task, "delay", _delay)

    result = tasks.poll_all_orders(platform="woocommerce")
    assert result["sites"] == 1
    assert dispatched == [[woo.id]]


@pytest.mark.django_db
def test_poll_all_orders_passes_date_range_to_batch(monkeypatch):
    """A requested date window is forwarded to each batch task verbatim."""
    from apps.sites.tests.factories import SiteFactory

    SiteFactory()

    monkeypatch.setattr(tasks, "_batch_size", lambda: 8)
    dispatched = []

    def _delay(chunk, status, date_from, date_to, run_id=None, triggered_by_id=None):
        dispatched.append((status, date_from, date_to))

    monkeypatch.setattr(tasks.poll_sites_batch_task, "delay", _delay)

    tasks.poll_all_orders(date_from="2026-06-01", date_to="2026-06-03")
    assert dispatched == [("processing", "2026-06-01", "2026-06-03")]


@pytest.mark.django_db
def test_poll_sites_batch_task_polls_each_site(monkeypatch):
    from apps.sites.tests.factories import SiteFactory

    s1, s2 = SiteFactory(), SiteFactory()
    calls = []

    def _fake_poll(site, status, date_from=None, date_to=None, run_id=None, triggered_by_id=None):
        calls.append((site.id, status, date_from, date_to))
        return {"site_id": site.id, "status": status, "fetched": 1}

    monkeypatch.setattr("apps.orders.services.poll_site", _fake_poll)

    result = tasks.poll_sites_batch_task(
        [s1.id, s2.id], "completed", "2026-06-01", "2026-06-03"
    )
    assert result["polled"] == 2
    assert result["status"] == "completed"
    assert sorted(c[0] for c in calls) == sorted([s1.id, s2.id])
    assert all(c[1] == "completed" for c in calls)
    # The date window reaches each poll_site call unchanged.
    assert all(c[2] == "2026-06-01" and c[3] == "2026-06-03" for c in calls)
