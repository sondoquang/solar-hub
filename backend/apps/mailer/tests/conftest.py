import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.mailer.models import MailSettings


@pytest.fixture(autouse=True)
def locmem_mail(settings):
    """Send through Django's in-memory backend — assert on ``mail.outbox``,
    never hit a real SMTP server."""
    settings.MAILER_EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="x")


@pytest.fixture
def client(user):
    """Authenticated API client (every Hub endpoint requires auth)."""
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def configured_settings(db):
    """A fully-configured MailSettings row (login + app password + recipients)."""
    s = MailSettings.load()
    s.smtp_host = "smtp.gmail.com"
    s.smtp_port = 587
    s.username = "shop@gmail.com"
    s.set_password("app-password-123")
    s.from_email = "shop@gmail.com"
    s.recipients = ["boss@example.com"]
    s.save()
    return s
