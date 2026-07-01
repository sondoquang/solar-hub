import pytest
from django.core import mail

from apps.mailer.models import MailSettings
from apps.orders.tests.factories import OrderFactory


@pytest.mark.django_db
def test_get_mail_settings_never_exposes_password(client, configured_settings):
    resp = client.get("/api/mail-settings/")
    assert resp.status_code == 200
    assert "password" not in resp.data
    assert "password_enc" not in resp.data
    assert resp.data["has_password"] is True
    assert resp.data["username"] == "shop@gmail.com"


@pytest.mark.django_db
def test_patch_updates_and_encrypts_password(client):
    resp = client.patch(
        "/api/mail-settings/",
        {
            "smtp_host": "smtp.gmail.com",
            "username": "me@gmail.com",
            "recipients": ["boss@example.com"],
            "password": "the-app-password",
        },
        format="json",
    )
    assert resp.status_code == 200
    assert "password" not in resp.data

    s = MailSettings.load()
    assert s.username == "me@gmail.com"
    assert s.recipients == ["boss@example.com"]
    assert s.get_password() == "the-app-password"  # stored encrypted, decrypts back


@pytest.mark.django_db
def test_patch_blank_password_keeps_existing(client, configured_settings):
    resp = client.patch(
        "/api/mail-settings/", {"from_name": "Solar", "password": ""}, format="json"
    )
    assert resp.status_code == 200
    assert MailSettings.load().get_password() == "app-password-123"


@pytest.mark.django_db
def test_patch_rejects_invalid_recipient_email(client):
    resp = client.patch(
        "/api/mail-settings/", {"recipients": ["not-an-email"]}, format="json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_patch_normalizes_digest_times(client):
    resp = client.patch(
        "/api/mail-settings/", {"digest_times": ["16:00", "9:05", "16:00"]}, format="json"
    )
    assert resp.status_code == 200
    # Zero-padded, de-duped, sorted.
    assert resp.data["digest_times"] == ["09:05", "16:00"]
    assert MailSettings.load().digest_times == ["09:05", "16:00"]


@pytest.mark.django_db
def test_patch_rejects_invalid_digest_time(client):
    resp = client.patch(
        "/api/mail-settings/", {"digest_times": ["09:00", "25:99"]}, format="json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_test_endpoint_sends_when_configured(client, configured_settings):
    resp = client.post(
        "/api/mail-settings/test/", {"recipient": "me@example.com"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["ok"] is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["me@example.com"]


@pytest.mark.django_db
def test_test_endpoint_sends_to_all_recipients(client, configured_settings):
    resp = client.post(
        "/api/mail-settings/test/",
        {"recipients": ["a@example.com", "b@example.com"]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["ok"] is True
    assert len(mail.outbox) == 1
    # Both addresses are on the single message's To header — not just the first.
    assert mail.outbox[0].to == ["a@example.com", "b@example.com"]


@pytest.mark.django_db
def test_test_endpoint_400_when_not_configured(client):
    resp = client.post(
        "/api/mail-settings/test/", {"recipient": "me@example.com"}, format="json"
    )
    assert resp.status_code == 400
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_orders_send_email_sends_selected(client, configured_settings):
    o1 = OrderFactory()
    o2 = OrderFactory()
    resp = client.post(
        "/api/orders/send_email/",
        {"recipient": "buyer@example.com", "ids": [o1.id, o2.id]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["sent"] == 2
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["buyer@example.com"]


@pytest.mark.django_db
def test_orders_send_email_rejects_bad_recipient(client, configured_settings):
    o1 = OrderFactory()
    resp = client.post(
        "/api/orders/send_email/",
        {"recipient": "nope", "ids": [o1.id]},
        format="json",
    )
    assert resp.status_code == 400
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_orders_send_email_requires_ids(client, configured_settings):
    resp = client.post(
        "/api/orders/send_email/",
        {"recipient": "buyer@example.com", "ids": []},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_orders_send_email_400_when_not_configured(client):
    o1 = OrderFactory()
    resp = client.post(
        "/api/orders/send_email/",
        {"recipient": "buyer@example.com", "ids": [o1.id]},
        format="json",
    )
    assert resp.status_code == 400
    assert len(mail.outbox) == 0
