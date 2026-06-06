import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="tester", password="x", first_name="Nguyễn", last_name="Văn A"
    )


@pytest.fixture
def client(user):
    """Authenticated API client (every Hub endpoint requires auth)."""
    api = APIClient()
    api.force_authenticate(user=user)
    return api
