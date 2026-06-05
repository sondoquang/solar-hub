import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def client(db):
    """Authenticated API client shared by all site/hosting API tests.

    Every Hub endpoint requires auth (settings DEFAULT_PERMISSION_CLASSES =
    IsAuthenticated), so tests must authenticate to exercise the real behaviour.
    """
    user = get_user_model().objects.create_user(username="tester", password="x")
    api = APIClient()
    api.force_authenticate(user=user)
    return api
