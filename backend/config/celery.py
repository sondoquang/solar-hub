import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("solar_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()  # discovers apps/*/tasks.py

# Health-check beat tick = the FAIL interval (the shortest cadence we need): each
# tick retries failed sites, while sites that passed are skipped until their
# longer OK interval elapses (the due-filter in apps.sites.services.check_hosting).
_HEALTHCHECK_TICK = float(os.getenv("SITE_HEALTHCHECK_FAIL_INTERVAL_SECONDS", "300"))

app.conf.beat_schedule = {
    "poll-all-orders": {
        "task": "apps.sync.tasks.poll_all_orders",
        "schedule": 180.0,  # every 3 min — fallback to webhooks
    },
    "check-all-sites": {
        "task": "apps.monitoring.tasks.check_all_sites",
        "schedule": _HEALTHCHECK_TICK,  # default 5 min — failed-site retry cadence
    },
}
