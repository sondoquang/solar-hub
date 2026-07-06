"""The seed migration ran on the test DB (pytest-django runs real migrations)."""

from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

seed = import_module("apps.accounts.migrations.0001_seed_default_groups").seed

pytestmark = pytest.mark.django_db


def test_default_groups_seeded():
    names = set(Group.objects.values_list("name", flat=True))
    assert {"Quản trị viên", "Nhân viên", "Marketing"} <= names

    admin = Group.objects.get(name="Quản trị viên")
    assert admin.permissions.count() == Permission.objects.count()

    marketing = Group.objects.get(name="Marketing")
    assert set(marketing.permissions.values_list("codename", flat=True)) == {
        "view_order",
        "view_masterproduct",
        "view_category",
        "view_site",
        "view_domaininfo",
        "view_healthcheck",
        "view_synclog",
    }

    staff = Group.objects.get(name="Nhân viên")
    staff_codenames = set(staff.permissions.values_list("codename", flat=True))
    assert "push_masterproduct" in staff_codenames
    assert "forward_order" in staff_codenames
    assert not any(c.startswith("delete_") for c in staff_codenames)
    assert not any(c.endswith("_user") or c.endswith("_group") for c in staff_codenames)


def test_seed_is_idempotent_and_grandfathers_users():
    user = get_user_model().objects.create_user(username="legacy", password="x")
    before = Group.objects.count()

    seed(django_apps, None)

    assert Group.objects.count() == before
    assert user.groups.filter(name="Quản trị viên").exists()
