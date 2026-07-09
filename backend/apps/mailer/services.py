"""Send synced orders by email — the twice-daily digest and the manual send.

Both paths build the same message: an HTML body (``render.py``) plus a PDF
attachment (``apps.orders.pdf.build_orders_pdf`` — one order per page). The SMTP
connection is built from the DB-stored :class:`~apps.mailer.models.MailSettings`
(host/port/login/app-password), not from Django ``EMAIL_*`` settings, so an admin
can change the account from the UI without a redeploy.

The scheduled digest only includes *genuine* orders (real customers); the manual
send respects whatever the admin selected. Errors carry no PII — only ids/counts.
"""

import datetime
import logging
import re

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.core.logging_utils import log_event
from apps.orders.models import GENUINE, Order
from apps.orders.pdf import build_orders_pdf

from .models import MailSettings
from .render import (
    render_orders_email_html,
    render_orders_email_text,
    render_product_sync_report_html,
    render_product_sync_report_text,
)

logger = logging.getLogger(__name__)

# Cap how many orders one email carries — keeps the body/PDF a sane size and
# avoids a single send timing out. A digest with more than this is unusual.
MAX_EMAIL_ORDERS = 200

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# Smtp backend used to actually send. Overridable (tests point it at locmem).
_DEFAULT_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


class MailNotConfigured(Exception):
    """SMTP account / recipients are incomplete — nothing was sent."""


def _backend_path() -> str:
    return getattr(settings, "MAILER_EMAIL_BACKEND", _DEFAULT_BACKEND)


def build_connection(s: MailSettings):
    """An SMTP connection from the stored settings (decrypts the app password)."""
    return mail.get_connection(
        backend=_backend_path(),
        host=s.smtp_host,
        port=s.smtp_port,
        username=s.username,
        password=s.get_password(),
        use_tls=s.use_tls,
        use_ssl=s.use_ssl,
    )


def normalize_recipients(value) -> list[str]:
    """Accept a string ("a@x, b@y") or a list; return a cleaned, de-duped list."""
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, list | tuple):
        parts = value
    else:
        parts = []
    out: list[str] = []
    for p in parts:
        addr = (p or "").strip()
        if addr and addr not in out:
            out.append(addr)
    return out


def resolve_product_sync_recipients(s: MailSettings) -> list[str]:
    """Who receives the product-sync report email.

    The dedicated ``product_sync_recipients`` list when set, otherwise a fallback
    to the order-digest ``recipients`` — so a Hub that only configured one list
    still gets the report."""
    return normalize_recipients(s.product_sync_recipients) or normalize_recipients(
        s.recipients
    )


_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_digest_times(value, *, strict: bool = False) -> list[str]:
    """Normalize a daily schedule to sorted, unique ``"HH:MM"`` strings.

    Accepts a list/tuple or a comma/space/semicolon-separated string. Each entry
    is zero-padded (``"9:0"`` → ``"09:00"``). Invalid entries raise ``ValueError``
    when ``strict`` (used by the serializer), or are skipped otherwise (a
    defensive read of stored data set via admin/shell).
    """
    if isinstance(value, str):
        items = re.split(r"[,;\s]+", value)
    elif isinstance(value, list | tuple):
        items = value
    else:
        items = []

    out: list[str] = []
    for raw in items:
        token = str(raw or "").strip()
        if not token:
            continue
        m = _TIME_RE.match(token)
        if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59:
            norm = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
            if norm not in out:
                out.append(norm)
            continue
        if strict:
            raise ValueError(f"Giờ không hợp lệ: {token!r} (định dạng HH:MM).")
    return sorted(out)


def send_orders_email(
    orders,
    recipients,
    *,
    subject: str | None = None,
    title: str = "Đơn hàng đồng bộ",
    settings_obj: MailSettings | None = None,
) -> int:
    """Send ``orders`` to ``recipients`` (HTML body + PDF attachment).

    Returns the number of orders sent. Raises :class:`MailNotConfigured` if the
    SMTP account is incomplete or there are no recipients. SMTP/connection errors
    propagate to the caller (mapped to a 502 by the API, retried by the task).
    """
    s = settings_obj or MailSettings.load()
    recipients = normalize_recipients(recipients)
    orders = list(orders)

    if not s.is_configured:
        raise MailNotConfigured("Chưa cấu hình tài khoản SMTP (email/mật khẩu).")
    if not recipients:
        raise MailNotConfigured("Chưa có địa chỉ email người nhận.")

    count = len(orders)
    if subject is None:
        subject = f"[Solar Hub] {count} đơn hàng — {title}"

    html_body = render_orders_email_html(orders, title=title)
    text_body = render_orders_email_text(orders)
    pdf_bytes = build_orders_pdf(orders)
    filename = (
        f"don-hang-{orders[0].number}.pdf" if count == 1 else "don-hang.pdf"
    )

    from_header = (
        f"{s.from_name} <{s.effective_from_email}>"
        if s.from_name
        else s.effective_from_email
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_header,
        to=recipients,
        connection=build_connection(s),
    )
    message.attach_alternative(html_body, "text/html")
    message.attach(filename, pdf_bytes, "application/pdf")
    message.send()

    logger.info(
        "mailer: sent %s order(s) to %s recipient(s)", count, len(recipients)
    )
    return count


def send_product_sync_report(
    detail: dict,
    xlsx_bytes: bytes,
    *,
    recipients,
    title: str | None = None,
    settings_obj: MailSettings | None = None,
) -> int:
    """Email one product-push run report (HTML body + .xlsx attachment).

    ``detail`` is ``apps.sync.services.product_run_detail`` output; ``xlsx_bytes``
    the ``build_product_run_workbook`` export. Returns the recipient count. Raises
    :class:`MailNotConfigured` when the SMTP account or recipients are incomplete;
    SMTP errors propagate (the task retries)."""
    from apps.sync.services import product_run_export_filename

    s = settings_obj or MailSettings.load()
    recipients = normalize_recipients(recipients)

    if not s.is_configured:
        raise MailNotConfigured("Chưa cấu hình tài khoản SMTP (email/mật khẩu).")
    if not recipients:
        raise MailNotConfigured("Chưa có địa chỉ email người nhận báo cáo đồng bộ.")

    started = detail.get("started_at")
    when = timezone.localtime(started).strftime("%d/%m/%Y %H:%M") if started else ""
    if title is None:
        title = f"Báo cáo đồng bộ sản phẩm {when}".strip()
    subject = f"[Solar Hub] {title}"

    html_body = render_product_sync_report_html(detail, title=title, meta=detail.get("meta"))
    text_body = render_product_sync_report_text(detail)
    filename = product_run_export_filename(detail)

    from_header = (
        f"{s.from_name} <{s.effective_from_email}>"
        if s.from_name
        else s.effective_from_email
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_header,
        to=recipients,
        connection=build_connection(s),
    )
    message.attach_alternative(html_body, "text/html")
    message.attach(filename, xlsx_bytes, XLSX_CONTENT_TYPE)
    message.send()

    logger.info(
        "mailer: sent product-sync report run_id=%s to %s recipient(s)",
        detail.get("run_id"),
        len(recipients),
    )
    return len(recipients)


def send_test_email(recipients, *, settings_obj: MailSettings | None = None) -> None:
    """A tiny "it works" email — verifies the SMTP account from the UI."""
    s = settings_obj or MailSettings.load()
    recipients = normalize_recipients(recipients) or normalize_recipients(s.recipients)
    if not s.is_configured:
        raise MailNotConfigured("Chưa cấu hình tài khoản SMTP (email/mật khẩu).")
    if not recipients:
        raise MailNotConfigured("Chưa có địa chỉ email người nhận.")

    from_header = (
        f"{s.from_name} <{s.effective_from_email}>"
        if s.from_name
        else s.effective_from_email
    )
    message = EmailMultiAlternatives(
        subject="[Solar Hub] Email thử nghiệm cấu hình SMTP",
        body=(
            "Đây là email thử nghiệm từ Solar Hub. "
            "Nếu bạn nhận được email này, cấu hình SMTP đã hoạt động."
        ),
        from_email=from_header,
        to=recipients,
        connection=build_connection(s),
    )
    message.send()
    logger.info("mailer: sent test email to %s recipient(s)", len(recipients))


def genuine_orders_since(since: datetime.datetime | None):
    """Genuine (real-customer) orders synced after ``since``, oldest first.

    "Synced" = the Hub ``created_at`` (when the upsert first stored the order),
    not the order's site-side creation time — so the digest reflects what was
    *newly pulled* in this window. Capped at ``MAX_EMAIL_ORDERS``.
    """
    qs = Order.objects.select_related("site", "site__hosting").filter(
        classification=GENUINE
    )
    if since is not None:
        qs = qs.filter(created_at__gt=since)
    return list(qs.order_by("created_at")[:MAX_EMAIL_ORDERS])


def _first_run_floor(now: datetime.datetime) -> datetime.datetime:
    """On the very first digest (no watermark), only look back this far so the
    first email doesn't dump the entire order history."""
    hours = getattr(settings, "MAIL_DIGEST_FIRST_RUN_LOOKBACK_HOURS", 24)
    return now - datetime.timedelta(hours=hours)


def send_digest(*, settings_obj: MailSettings | None = None) -> dict:
    """The twice-daily job: email genuine orders synced since the last digest.

    Skips (without raising) when disabled, unconfigured, or there are no new
    orders. Advances the watermark whenever it actually looks at a window, so the
    next run never re-sends the same orders.
    """
    s = settings_obj or MailSettings.load()
    now = timezone.now()

    if not s.digest_enabled:
        return {"sent": 0, "skipped": "disabled"}
    if not s.is_configured:
        logger.warning("mailer: digest skipped — SMTP not configured")
        return {"sent": 0, "skipped": "not_configured"}
    recipients = normalize_recipients(s.recipients)
    if not recipients:
        logger.warning("mailer: digest skipped — no recipients")
        return {"sent": 0, "skipped": "no_recipients"}

    since = s.last_digest_sent_at or _first_run_floor(now)
    orders = genuine_orders_since(since)

    if not orders:
        # Nothing new — still advance the watermark so the window doesn't grow.
        s.last_digest_sent_at = now
        s.save(update_fields=["last_digest_sent_at", "updated_at"])
        return {"sent": 0, "skipped": "no_new_orders"}

    title = f"Báo cáo đơn hàng {now.astimezone().strftime('%d/%m/%Y %H:%M')}"
    send_orders_email(orders, recipients, title=title, settings_obj=s)

    s.last_digest_sent_at = now
    s.save(update_fields=["last_digest_sent_at", "updated_at"])
    log_event(
        logger, logging.INFO, "send_digest ok",
        sent=len(orders), recipients=len(recipients),
    )
    return {"sent": len(orders), "recipients": len(recipients)}


def _most_recent_due_slot(
    now: datetime.datetime, times: list[str]
) -> datetime.datetime | None:
    """The latest scheduled datetime today at/just before ``now`` (``None`` if
    no slot has come due yet today). ``now`` and the result are in local time."""
    due: datetime.datetime | None = None
    for t in times:
        hh, mm = (int(x) for x in t.split(":"))
        slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if slot <= now and (due is None or slot > due):
            due = slot
    return due


def run_scheduled_digest(
    *, settings_obj: MailSettings | None = None, now: datetime.datetime | None = None
) -> dict:
    """Send the digest only if a configured time slot is due and not yet sent.

    Driven by a minute-level Beat tick (``tasks.dispatch_due_digests``): on each
    tick it finds the most recent ``digest_times`` slot that has passed today and
    fires :func:`send_digest` when the watermark predates that slot. The ``<=``
    comparison makes it self-healing — if Beat misses the exact minute, the next
    tick still catches the slot. Gating checks here are quiet (no logging) so a
    misconfigured account doesn't spam the log once a minute.
    """
    s = settings_obj or MailSettings.load()
    if not s.digest_enabled:
        return {"sent": 0, "skipped": "disabled"}
    if not s.is_configured:
        return {"sent": 0, "skipped": "not_configured"}
    if not normalize_recipients(s.recipients):
        return {"sent": 0, "skipped": "no_recipients"}

    times = parse_digest_times(s.digest_times)
    if not times:
        return {"sent": 0, "skipped": "no_schedule"}

    now = now or timezone.localtime()
    slot = _most_recent_due_slot(now, times)
    if slot is None:
        return {"sent": 0, "skipped": "not_due"}
    if s.last_digest_sent_at is not None and s.last_digest_sent_at >= slot:
        return {"sent": 0, "skipped": "already_sent"}

    return send_digest(settings_obj=s)
