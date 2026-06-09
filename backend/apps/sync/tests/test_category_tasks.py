import pytest

from apps.sync import tasks


@pytest.mark.django_db
def test_pull_all_categories_chunks_into_batches(monkeypatch):
    """All non-deleted sites are split into batches of ORDER_POLL_BATCH_SIZE."""
    from apps.sites.tests.factories import SiteFactory

    sites = [SiteFactory() for _ in range(5)]
    ids = sorted(s.id for s in sites)

    monkeypatch.setattr(tasks, "_batch_size", lambda: 2)
    dispatched = []
    monkeypatch.setattr(
        tasks.pull_categories_batch_task,
        "delay",
        lambda chunk: dispatched.append(chunk),
    )

    result = tasks.pull_all_categories()
    assert result == {"sites": 5, "batches": 3}
    assert [len(c) for c in dispatched] == [2, 2, 1]
    assert sorted(i for c in dispatched for i in c) == ids


@pytest.mark.django_db
def test_pull_all_categories_filters_to_selected_sites(monkeypatch):
    from apps.sites.tests.factories import SiteFactory

    keep = SiteFactory()
    SiteFactory()  # excluded

    monkeypatch.setattr(tasks, "_batch_size", lambda: 8)
    dispatched = []
    monkeypatch.setattr(
        tasks.pull_categories_batch_task,
        "delay",
        lambda chunk: dispatched.append(chunk),
    )

    result = tasks.pull_all_categories(site_ids=[keep.id])
    assert result == {"sites": 1, "batches": 1}
    assert dispatched == [[keep.id]]


@pytest.mark.django_db
def test_pull_all_categories_skips_if_already_running(monkeypatch):
    """A second full-site pull while one is already in flight is a no-op."""
    from apps.sites.tests.factories import SiteFactory

    SiteFactory()
    monkeypatch.setattr(tasks, "_batch_size", lambda: 8)
    monkeypatch.setattr(tasks.pull_categories_batch_task, "delay", lambda chunk: None)

    result1 = tasks.pull_all_categories()
    assert result1["sites"] == 1

    # Lock is still held → second call skipped.
    result2 = tasks.pull_all_categories()
    assert result2 == {"status": "skipped_already_running", "sites": 0, "batches": 0}


@pytest.mark.django_db
def test_pull_categories_batch_task_pulls_each_site(monkeypatch):
    from apps.sites.tests.factories import SiteFactory

    s1, s2 = SiteFactory(), SiteFactory()
    calls = []

    def _fake_pull(site):
        calls.append(site.id)
        return {"site_id": site.id, "pulled": 1}

    monkeypatch.setattr("apps.catalog.services.pull_categories_for_site", _fake_pull)

    result = tasks.pull_categories_batch_task([s1.id, s2.id])
    assert result["pulled"] == 2
    assert sorted(calls) == sorted([s1.id, s2.id])
