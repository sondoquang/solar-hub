from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from celery import shared_task


@shared_task
def refresh_all_domain_info(force=False, queue=None):
    """Dispatch domain-info refreshes in batches.

    The periodic beat runs this with defaults — only sites whose snapshot is
    stale (older than DOMAIN_INFO_REFRESH_INTERVAL_SECONDS) are selected, so
    the hourly tick self-heals without hammering registries. The UI's
    "Làm mới tất cả" calls it with ``force=True`` + ``queue="interactive"`` so
    user-triggered work never sits behind periodic jobs.
    """
    from django.conf import settings
    from django.db.models import Q
    from django.utils import timezone

    from apps.sites.models import Site

    qs = Site.objects.filter(is_deleted=False)
    if not force:
        cutoff = timezone.now() - timedelta(
            seconds=settings.DOMAIN_INFO_REFRESH_INTERVAL_SECONDS
        )
        qs = qs.filter(
            Q(domain_info__isnull=True)
            | Q(domain_info__last_refreshed_at__isnull=True)
            | Q(domain_info__last_refreshed_at__lte=cutoff)
        )
    ids = list(qs.order_by("id").values_list("id", flat=True))
    size = max(1, settings.DOMAIN_INFO_BATCH_SIZE)
    chunks = [ids[i : i + size] for i in range(0, len(ids), size)]
    opts = {"queue": queue} if queue else {}
    for chunk in chunks:
        refresh_domain_batch.apply_async(args=[chunk], kwargs={"force": force}, **opts)
    return {"sites": len(ids), "batches": len(chunks)}


@shared_task
def refresh_domain_batch(site_ids, force=False):
    """Refresh one batch of sites, DOMAIN_INFO_WORKERS domains at a time."""
    from django.conf import settings
    from django.db import connection

    from apps.sites.models import Site

    from . import services

    def worker(site):
        try:
            services.refresh_domain_info(site, force=force)
            return site.id
        finally:
            # Each worker thread opens its own (thread-local) DB connection;
            # close it so the pool does not leak connections every round.
            connection.close()

    sites = list(Site.objects.filter(id__in=site_ids, is_deleted=False))
    if not sites:
        return {"refreshed": 0}
    workers = max(1, settings.DOMAIN_INFO_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        done = list(executor.map(worker, sites))
    return {"refreshed": len(done)}


@shared_task
def refresh_site_domain_info(site_id, checks=None):
    """Single-site refresh behind the manual "Làm mới" button (the view enqueues
    this on the "interactive" queue). ``force=True``: a user asking explicitly
    bypasses the Google-index cadence."""
    from apps.sites.models import Site

    from . import services

    site = Site.objects.filter(id=site_id, is_deleted=False).first()
    if site is None:
        return {"refreshed": 0}
    services.refresh_domain_info(site, checks=checks, force=True)
    return {"refreshed": 1}
