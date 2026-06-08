import pytest

from apps.sync import tasks


@pytest.mark.django_db
def test_push_all_products_chunks_into_batches(monkeypatch):
    """All non-deleted sites are split into batches of PRODUCT_PUSH_BATCH_SIZE."""
    from apps.sites.tests.factories import SiteFactory

    sites = [SiteFactory() for _ in range(5)]
    ids = sorted(s.id for s in sites)

    monkeypatch.setattr(tasks, "_push_batch_size", lambda: 2)
    dispatched = []
    monkeypatch.setattr(
        tasks.push_products_batch_task,
        "delay",
        lambda chunk, master_ids: dispatched.append((chunk, master_ids)),
    )

    result = tasks.push_all_products(master_ids=[7, 8])
    assert result == {"sites": 5, "batches": 3}
    assert [len(c) for c, _ in dispatched] == [2, 2, 1]
    assert sorted(i for c, _ in dispatched for i in c) == ids
    assert all(m == [7, 8] for _, m in dispatched)


@pytest.mark.django_db
def test_push_all_products_filters_to_selected_sites(monkeypatch):
    from apps.sites.tests.factories import SiteFactory

    keep = SiteFactory()
    SiteFactory()  # excluded

    monkeypatch.setattr(tasks, "_push_batch_size", lambda: 8)
    dispatched = []
    monkeypatch.setattr(
        tasks.push_products_batch_task,
        "delay",
        lambda chunk, master_ids: dispatched.append((chunk, master_ids)),
    )

    result = tasks.push_all_products(site_ids=[keep.id])
    assert result == {"sites": 1, "batches": 1}
    assert dispatched == [([keep.id], None)]


@pytest.mark.django_db
def test_push_products_batch_task_pushes_each_site(monkeypatch):
    from apps.sites.tests.factories import SiteFactory

    s1, s2 = SiteFactory(), SiteFactory()
    calls = []

    def _fake_push(site, masters=None):
        calls.append((site.id, masters))
        return {"site_id": site.id, "created": 1}

    monkeypatch.setattr("apps.catalog.services.push_products_to_site", _fake_push)

    result = tasks.push_products_batch_task([s1.id, s2.id])
    assert result["pushed"] == 2
    assert sorted(c[0] for c in calls) == sorted([s1.id, s2.id])
    # No master_ids → push the whole catalog (masters=None).
    assert all(c[1] is None for c in calls)
