import uuid

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


def _run_detail(**over):
    """A minimal product_run_detail-shaped dict for the report email/xlsx."""
    site = {
        "site_id": 1,
        "site_name": "A-Site",
        "site_url": "https://a-site.example",
        "hosting": "TenTen",
        "hosting_name": "TenTen",
        "hosting_username": "acc_01",
        "status": "partial",
        "error": "",
        "created": 3,
        "updated": 1,
        "deleted": 0,
        "planned": 4,
        "adopted_count": 1,
        "adopted": [],
        "ambiguous": [],
        "recreated_stale": 0,
        "variations": {},
        "failed": [
            {"sku": "SP-1", "op": "create", "code": "x", "message": "boom", "kind": "error"}
        ],
        "created_at": timezone.now(),
    }
    detail = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "started_at": timezone.now(),
        "site_count": 1,
        "total_created": 3,
        "total_updated": 1,
        "total_deleted": 0,
        "total_adopted": 1,
        "total_failed": 1,
        "error_count": 0,
        "status": "partial",
        "duration_seconds": 5,
        "triggered_by": "Admin",
        "site_label": None,
        "meta": {"all_products": True},
        "sites": [site],
    }
    detail.update(over)
    return detail


@pytest.mark.django_db
def test_send_product_sync_report_builds_html_and_xlsx(configured_settings):
    from apps.sync.services import build_product_run_workbook

    detail = _run_detail()
    xlsx = build_product_run_workbook(detail)
    sent = services.send_product_sync_report(
        detail, xlsx, recipients=["ops@example.com"], settings_obj=configured_settings
    )

    assert sent == 1
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["ops@example.com"]
    assert any(ct == "text/html" for _, ct in msg.alternatives)
    # A single .xlsx attachment with the spreadsheet mimetype.
    assert len(msg.attachments) == 1
    name, content, mimetype = msg.attachments[0]
    assert name.endswith(".xlsx")
    assert mimetype == services.XLSX_CONTENT_TYPE
    # A real zip-based xlsx starts with the PK signature.
    assert content[:2] == b"PK"


@pytest.mark.django_db
def test_send_product_sync_report_requires_configuration():
    with pytest.raises(services.MailNotConfigured):
        services.send_product_sync_report(_run_detail(), b"x", recipients=["a@b.com"])


@pytest.mark.django_db
def test_send_product_sync_report_requires_recipients(configured_settings):
    with pytest.raises(services.MailNotConfigured):
        services.send_product_sync_report(
            _run_detail(), b"x", recipients=[], settings_obj=configured_settings
        )


@pytest.mark.django_db
def test_resolve_product_sync_recipients_prefers_dedicated_then_falls_back():
    s = MailSettings.load()
    s.recipients = ["digest@example.com"]
    s.product_sync_recipients = []
    s.save()
    # Empty dedicated list → fall back to the order-digest recipients.
    assert services.resolve_product_sync_recipients(s) == ["digest@example.com"]

    s.product_sync_recipients = ["sync@example.com"]
    s.save()
    # Set → the dedicated list wins.
    assert services.resolve_product_sync_recipients(s) == ["sync@example.com"]


@pytest.mark.django_db
def test_product_sync_report_task_sends_once_and_claims(configured_settings, monkeypatch):
    from apps.sites.tests.factories import SiteFactory
    from apps.sync.models import Notification, SyncLog
    from apps.sync.tasks import send_product_sync_report_task

    # The task closes its DB connection in a finally; no-op it so it doesn't tear
    # down the test's wrapping transaction.
    monkeypatch.setattr("apps.sync.tasks.connection.close", lambda: None)

    configured_settings.product_sync_recipients = ["ops@example.com"]
    configured_settings.save()

    run_id = uuid.uuid4()
    site = SiteFactory(name="A-Site")
    SyncLog.objects.create(
        site=site,
        operation="push_products",
        status=SyncLog.Status.SUCCESS,
        run_id=run_id,
        created_count=2,
        detail={"site_name": site.name},
    )
    notif = Notification.objects.create(
        run_id=run_id, operation="push_products", expected=1, summary={"all_products": True}
    )

    res = send_product_sync_report_task.apply(args=[str(run_id)]).get()
    assert res["status"] == "sent"
    assert len(mail.outbox) == 1
    notif.refresh_from_db()
    assert notif.report_emailed_at is not None

    # Re-running is claimed out (already sent) — no duplicate email.
    res2 = send_product_sync_report_task.apply(args=[str(run_id)]).get()
    assert res2["status"] == "already_sent"
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_product_sync_report_task_skips_when_disabled(configured_settings, monkeypatch):
    from apps.sync.models import Notification
    from apps.sync.tasks import send_product_sync_report_task

    monkeypatch.setattr("apps.sync.tasks.connection.close", lambda: None)
    configured_settings.product_sync_report_enabled = False
    configured_settings.save()

    run_id = uuid.uuid4()
    Notification.objects.create(run_id=run_id, operation="push_products", expected=1)

    res = send_product_sync_report_task.apply(args=[str(run_id)]).get()
    assert res["status"] == "disabled"
    assert len(mail.outbox) == 0


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
