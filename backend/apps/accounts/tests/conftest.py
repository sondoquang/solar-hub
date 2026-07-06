import itertools

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

_seq = itertools.count()


@pytest.fixture
def admin_client(db):
    user = get_user_model().objects.create_superuser(
        username="rbac_admin", password="x"
    )
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def plain_client(db):
    """Authenticated user with ZERO permissions."""
    user = get_user_model().objects.create_user(username="rbac_plain", password="x")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def perm_client(db):
    """Factory: APIClient authenticated as a user holding exactly the given
    permission codenames (attached directly — RBAC reads groups AND user
    perms through ``has_perms``). The user is exposed as ``client.user``."""

    def make(*codenames):
        user = get_user_model().objects.create_user(
            username=f"rbac_user_{next(_seq)}", password="x"
        )
        if codenames:
            perms = list(Permission.objects.filter(codename__in=codenames))
            missing = set(codenames) - {p.codename for p in perms}
            assert not missing, f"unknown permission codenames: {missing}"
            user.user_permissions.set(perms)
        api = APIClient()
        api.force_authenticate(user=user)
        api.user = user
        return api

    return make
