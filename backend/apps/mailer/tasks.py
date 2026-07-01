"""Periodic mail tasks.

``dispatch_due_digests`` is wired to Celery Beat (config/celery.py) to run every
minute: it checks the admin-configured ``MailSettings.digest_times`` and emails
the genuine orders synced since the last run when a time slot is due. Letting one
cheap tick decide keeps the schedule editable from the UI (no redeploy) and lets
it self-heal if Beat misses the exact minute.

``send_order_digest`` is the unconditional "send now" variant (ignores the
schedule) — handy for an admin action or a shell. Manual order sends go straight
through the API (synchronous, like complete/cancel) and don't need a task.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def dispatch_due_digests():
    """Send the digest if a configured time slot is due (minute-level Beat tick)."""
    from .services import run_scheduled_digest

    result = run_scheduled_digest()
    # Only log when something was actually sent — this runs every minute.
    if result.get("sent"):
        logger.info("mailer: scheduled digest result=%s", result)
    return result


@shared_task
def send_order_digest():
    """Send the order digest now for the window since the last digest (no schedule)."""
    from .services import send_digest

    result = send_digest()
    logger.info("mailer: digest run result=%s", result)
    return result
