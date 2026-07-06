import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("solar_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()  # discovers apps/*/tasks.py

# Health-check beat tick = the FAIL interval (the shortest cadence we need): each
# tick retries failed sites, while sites that passed are skipped until their
# longer OK interval elapses (the due-filter in apps.sites.services.check_hosting).
_HEALTHCHECK_TICK = float(os.getenv("SITE_HEALTHCHECK_FAIL_INTERVAL_SECONDS", "300"))
_ORDER_POLL_INTERVAL = float(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "480"))
# Domain-info tick is deliberately much shorter than the per-site refresh
# interval (default 24h): each tick the dispatcher re-selects only STALE sites,
# so new sites and previously-failed runs self-heal within the hour.
_DOMAIN_INFO_TICK = float(os.getenv("DOMAIN_INFO_TICK_SECONDS", "3600"))

@task_postrun.connect
def close_db_connections(**kwargs):
    from django.db import close_old_connections
    close_old_connections()


app.conf.beat_schedule = {
    "poll-all-orders": {
        "task": "apps.sync.tasks.poll_all_orders",
        "schedule": _ORDER_POLL_INTERVAL,  # default 8 min — fallback to webhooks
    },
    "check-all-sites": {
        "task": "apps.monitoring.tasks.check_all_sites",
        "schedule": _HEALTHCHECK_TICK,  # default 5 min — failed-site retry cadence
    },
    # Email the genuine orders synced since the last run on an admin-configurable
    # daily schedule. This tick fires every minute and the task itself decides
    # whether a `MailSettings.digest_times` slot (local time, CELERY_TIMEZONE =
    # Asia/Ho_Chi_Minh) is due — so the times are editable from the UI without a
    # redeploy, and a missed minute self-heals on the next tick.
    "mailer-digest-tick": {
        "task": "apps.mailer.tasks.dispatch_due_digests",
        "schedule": crontab(minute="*"),
    },
    # Primary finalizer for push notifications now that the frontend no longer
    # polls: flip RUNNING → completed/timeout (which also queues the report email).
    # Every minute so a completed push is reported by email within ~1 min.
    "finalize-push-notifications": {
        "task": "apps.sync.tasks.finalize_push_notifications",
        "schedule": 60.0,  # every 1 min
    },
    # Domain snapshots (WHOIS/DNS/SSL/blacklist/Google index). Hourly tick;
    # the task itself filters to sites not refreshed in the last 24h.
    "refresh-domain-info": {
        "task": "apps.domains.tasks.refresh_all_domain_info",
        "schedule": _DOMAIN_INFO_TICK,
    },
}
