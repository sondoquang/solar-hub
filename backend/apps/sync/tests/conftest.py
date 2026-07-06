import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def user(db):
    # Superuser: business tests bypass RBAC (covered in apps/accounts/tests).
    return get_user_model().objects.create_superuser(username="tester", password="x")


@pytest.fixture
def client(user):
    """Authenticated API client (every Hub endpoint requires auth)."""
    api = APIClient()
    api.force_authenticate(user=user)
    return api
