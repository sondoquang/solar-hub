import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def client(db):
    """Authenticated API client shared by all site/hosting API tests.

    Every Hub endpoint requires auth + model permissions (settings
    DEFAULT_PERMISSION_CLASSES = RBACPermission), so business tests run as a
    superuser; the RBAC layer itself is covered in apps/accounts/tests.
    """
    user = get_user_model().objects.create_superuser(username="tester", password="x")
    api = APIClient()
    api.force_authenticate(user=user)
    return api
