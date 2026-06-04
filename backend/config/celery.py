import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("solar_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()  # discovers apps/*/tasks.py

app.conf.beat_schedule = {
    "poll-all-orders": {
        "task": "apps.sync.tasks.poll_all_orders",
        "schedule": 180.0,  # every 3 min — fallback to webhooks
    },
    "check-all-sites": {
        "task": "apps.monitoring.tasks.check_all_sites",
        "schedule": 300.0,  # every 5 min — site healthcheck
    },
}
