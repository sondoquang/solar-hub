import pytest

from apps.monitoring import tasks

from .factories import HostingFactory, SiteFactory


@pytest.mark.django_db
def test_check_all_sites_dispatches_one_task_per_hosting(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        tasks.check_hosting_task, "delay", lambda hosting_id: dispatched.append(hosting_id)
    )
    h1, h2 = HostingFactory(), HostingFactory()
    SiteFactory(hosting=h1)
    SiteFactory(hosting=h2)
    SiteFactory(hosting=None)  # orphan → triggers the None group

    result = tasks.check_all_sites()

    assert result == {"dispatched": 3}
    assert set(dispatched) == {h1.id, h2.id, None}


@pytest.mark.django_db
def test_check_all_sites_skips_none_group_when_no_orphans(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        tasks.check_hosting_task, "delay", lambda hosting_id: dispatched.append(hosting_id)
    )
    hosting = HostingFactory()
    SiteFactory(hosting=hosting)

    tasks.check_all_sites()

    assert dispatched == [hosting.id]


@pytest.mark.django_db
def test_check_all_sites_ignores_deleted_hosting(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        tasks.check_hosting_task, "delay", lambda hosting_id: dispatched.append(hosting_id)
    )
    HostingFactory(is_deleted=True)

    result = tasks.check_all_sites()

    assert result == {"dispatched": 0}
    assert dispatched == []
