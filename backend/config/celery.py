import logging
import os
import time

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_postrun, task_prerun

from apps.core.logging_utils import log_event  # dependency-free (stdlib logging only)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# One place to log EVERY task's start/ok/fail + duration (the "task layer"
# counterpart of RequestLogMiddleware) — no need to edit each task body. Task
# args/kwargs are NOT logged (they can carry PII / large payloads); only the
# task name, id, state and elapsed time.
task_logger = logging.getLogger("apps.task")
_task_started: dict[str, float] = {}

app = Celery("solar_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
# Keep Django's LOGGING dictConfig (settings.py) authoritative: without this,
# Celery reconfigures the root logger and our per-module handlers/format are lost.
app.conf.worker_hijack_root_logger = False
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

@task_prerun.connect
def _log_task_start(task_id=None, task=None, **kwargs):
    _task_started[task_id] = time.perf_counter()
    log_event(task_logger, logging.INFO, "task start", name=getattr(task, "name", None), id=task_id)


@task_postrun.connect
def _log_task_end(task_id=None, task=None, state=None, **kwargs):
    started = _task_started.pop(task_id, None)
    elapsed_ms = int((time.perf_counter() - started) * 1000) if started is not None else None
    # SUCCESS at INFO; anything else (e.g. RETRY/REVOKED) at WARNING. FAILURE is
    # logged with its traceback by _log_task_failure below.
    level = logging.INFO if state == "SUCCESS" else logging.WARNING
    log_event(
        task_logger, level, "task end",
        name=getattr(task, "name", None), id=task_id, state=state, elapsed_ms=elapsed_ms,
    )


@task_failure.connect
def _log_task_failure(task_id=None, exception=None, sender=None, **kwargs):
    _task_started.pop(task_id, None)
    log_event(
        task_logger, logging.ERROR, "task fail",
        name=getattr(sender, "name", None), id=task_id,
        err=type(exception).__name__ if exception else None,
        exc_info=True,
    )


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
