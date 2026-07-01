import pytest
from django.core import mail
from django.utils import timezone

from apps.mailer import services
from apps.mailer.models import MailSettings
from apps.orders.models import Order
from apps.orders.tests.factories import OrderFactory


def _backdate(order, dt):
    """created_at is auto_now_add — override it to simulate an older sync."""
    Order.objects.filter(pk=order.pk).update(created_at=dt)


@pytest.mark.django_db
def test_genuine_orders_since_filters_classification():
    OrderFactory(classification="genuine")
    OrderFactory(classification="suspicious")
    OrderFactory(classification="spam")
    orders = services.genuine_orders_since(None)
    assert len(orders) == 1
    assert orders[0].classification == "genuine"


@pytest.mark.django_db
def test_genuine_orders_since_excludes_older_than_watermark():
    since = timezone.now() - timezone.timedelta(hours=1)
    old = OrderFactory(classification="genuine")
    _backdate(old, since - timezone.timedelta(hours=2))
    new = OrderFactory(classification="genuine")  # created_at = now > since
    orders = services.genuine_orders_since(since)
    assert [o.id for o in orders] == [new.id]


@pytest.mark.django_db
def test_send_orders_email_builds_html_and_pdf(configured_settings):
    orders = [OrderFactory(), OrderFactory()]
    sent = services.send_orders_email(orders, ["a@b.com"], settings_obj=configured_settings)

    assert sent == 2
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["a@b.com"]
    # HTML alternative present…
    assert any(ct == "text/html" for _, ct in msg.alternatives)
    # …and a single PDF attachment.
    attachments = msg.attachments
    assert len(attachments) == 1
    name, content, mimetype = attachments[0]
    assert name.endswith(".pdf")
    assert mimetype == "application/pdf"
    assert content[:4] == b"%PDF"


@pytest.mark.django_db
def test_send_orders_email_requires_configuration():
    with pytest.raises(services.MailNotConfigured):
        services.send_orders_email([OrderFactory()], ["a@b.com"])


@pytest.mark.django_db
def test_send_orders_email_requires_recipients(configured_settings):
    with pytest.raises(services.MailNotConfigured):
        services.send_orders_email([OrderFactory()], [], settings_obj=configured_settings)


@pytest.mark.django_db
def test_digest_sends_only_genuine_and_advances_watermark(configured_settings):
    configured_settings.last_digest_sent_at = timezone.now() - timezone.timedelta(hours=2)
    configured_settings.save()

    OrderFactory(classification="genuine")
    OrderFactory(classification="genuine")
    OrderFactory(classification="spam")

    result = services.send_digest()

    assert result["sent"] == 2
    assert len(mail.outbox) == 1
    # Watermark advanced so the next run won't re-send these.
    s = MailSettings.load()
    assert s.last_digest_sent_at is not None
    assert services.send_digest()["skipped"] == "no_new_orders"


@pytest.mark.django_db
def test_digest_skips_when_disabled(configured_settings):
    configured_settings.digest_enabled = False
    configured_settings.save()
    assert services.send_digest()["skipped"] == "disabled"
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_digest_skips_when_not_configured():
    MailSettings.load()  # exists but empty
    OrderFactory(classification="genuine")
    assert services.send_digest()["skipped"] == "not_configured"
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_digest_skips_when_no_recipients(configured_settings):
    configured_settings.recipients = []
    configured_settings.save()
    assert services.send_digest()["skipped"] == "no_recipients"
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_normalize_recipients_handles_string_and_dedup():
    assert services.normalize_recipients("a@x.com, b@y.com; a@x.com") == [
        "a@x.com",
        "b@y.com",
    ]
    assert services.normalize_recipients(["a@x.com", " ", "b@y.com"]) == [
        "a@x.com",
        "b@y.com",
    ]


def test_parse_digest_times_normalizes_dedups_sorts():
    # Zero-pads the hour, de-dupes, sorts; accepts list or separated string.
    assert services.parse_digest_times(["16:00", "9:05", "16:00"]) == ["09:05", "16:00"]
    assert services.parse_digest_times("09:00, 16:00; 09:00") == ["09:00", "16:00"]
    # Lenient mode drops junk; strict mode rejects it.
    assert services.parse_digest_times(["09:00", "nope", "25:00"]) == ["09:00"]
    with pytest.raises(ValueError):
        services.parse_digest_times(["09:00", "nope"], strict=True)


@pytest.mark.django_db
def test_run_scheduled_digest_fires_when_slot_due(configured_settings):
    configured_settings.digest_times = ["09:00", "16:00"]
    configured_settings.last_digest_sent_at = timezone.now() - timezone.timedelta(days=1)
    configured_settings.save()
    OrderFactory(classification="genuine")

    # Pin "now" just after the 09:00 slot.
    now = timezone.localtime().replace(hour=9, minute=1, second=0, microsecond=0)
    result = services.run_scheduled_digest(now=now)

    assert result["sent"] == 1
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_run_scheduled_digest_skips_before_first_slot(configured_settings):
    configured_settings.digest_times = ["09:00", "16:00"]
    configured_settings.save()
    OrderFactory(classification="genuine")

    now = timezone.localtime().replace(hour=8, minute=30, second=0, microsecond=0)
    assert services.run_scheduled_digest(now=now)["skipped"] == "not_due"
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_run_scheduled_digest_does_not_resend_same_slot(configured_settings):
    configured_settings.digest_times = ["09:00", "16:00"]
    configured_settings.last_digest_sent_at = timezone.now() - timezone.timedelta(days=1)
    configured_settings.save()
    OrderFactory(classification="genuine")

    now = timezone.localtime().replace(hour=9, minute=1, second=0, microsecond=0)
    assert services.run_scheduled_digest(now=now)["sent"] == 1
    # A later tick in the same slot window must not re-send.
    later = now.replace(minute=30)
    assert services.run_scheduled_digest(now=later)["skipped"] == "already_sent"
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_run_scheduled_digest_skips_when_disabled(configured_settings):
    configured_settings.digest_enabled = False
    configured_settings.save()
    now = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
    assert services.run_scheduled_digest(now=now)["skipped"] == "disabled"
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_run_scheduled_digest_skips_with_empty_schedule(configured_settings):
    configured_settings.digest_times = []
    configured_settings.save()
    now = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
    assert services.run_scheduled_digest(now=now)["skipped"] == "no_schedule"
    assert len(mail.outbox) == 0
