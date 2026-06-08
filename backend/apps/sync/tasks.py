from concurrent.futures import ThreadPoolExecutor

from celery import shared_task
from django.conf import settings
from django.db import connection


def _batch_size() -> int:
    """Sites polled concurrently per batch task (settings, default 8, min 1)."""
    return max(1, getattr(settings, "ORDER_POLL_BATCH_SIZE", 8))


def _push_batch_size() -> int:
    """Sites pushed concurrently per batch task (settings, default 8, min 1)."""
    return max(1, getattr(settings, "PRODUCT_PUSH_BATCH_SIZE", 8))


@shared_task
def poll_all_orders(status=None, site_ids=None, date_from=None, date_to=None):
    """Poll orders of ONE ``status`` across sites, split into concurrent batches.

    Periodic (Celery Beat, every ~3 min) it runs with the default status
    (``processing``) over all sites — the fallback to webhooks. The "Đồng bộ
    ngay" UI passes a specific ``status`` (and optionally ``site_ids`` and a
    ``date_from``/``date_to`` window) to sync another status on demand. One run
    = exactly one status (best performance).

    Sites are chunked into batches of ``ORDER_POLL_BATCH_SIZE`` (8) and one
    ``poll_sites_batch_task`` is dispatched per chunk, so a slow/broken site
    only holds up its own batch. The upsert is idempotent, so overlap with a
    future webhook is safe.
    """
    from apps.orders.services import POLL_STATUS
    from apps.sites.models import Site

    status = status or POLL_STATUS

    qs = Site.objects.filter(is_deleted=False)
    if site_ids is not None:
        qs = qs.filter(id__in=site_ids)
    ids = list(qs.values_list("id", flat=True))

    size = _batch_size()
    batches = [ids[i : i + size] for i in range(0, len(ids), size)]
    for chunk in batches:
        poll_sites_batch_task.delay(chunk, status, date_from, date_to)
    return {"status": status, "sites": len(ids), "batches": len(batches)}


@shared_task
def poll_sites_batch_task(site_ids, status, date_from=None, date_to=None):
    """Poll one status for a batch of sites, ``ORDER_POLL_BATCH_SIZE`` at a time.

    Mirrors apps/sites/services.check_hosting: a ThreadPoolExecutor caps how
    many sites hit the network at once. ``poll_site`` swallows network errors
    into its result (never raises), so one bad site does not abort the batch.
    """
    from apps.orders import services
    from apps.sites.models import Site

    sites = list(Site.objects.filter(id__in=site_ids, is_deleted=False))
    if not sites:
        return {"status": status, "polled": 0, "results": []}

    def _poll(site):
        return services.poll_site(site, status, date_from=date_from, date_to=date_to)

    with ThreadPoolExecutor(max_workers=_batch_size()) as executor:
        results = list(executor.map(_poll, sites))
    return {"status": status, "polled": len(results), "results": results}


@shared_task
def push_all_products(site_ids=None, master_ids=None):
    """Push the catalog to sites, split into concurrent batches ("Sync all").

    The "Đồng bộ ngay" UI (or admin action) triggers this. ``site_ids`` scopes
    which sites to push to (all live sites when omitted); ``master_ids`` scopes
    which products (the whole catalog when omitted). Sites are chunked into
    batches of ``PRODUCT_PUSH_BATCH_SIZE`` and one ``push_products_batch_task`` is
    dispatched per chunk, so a slow/broken site only holds up its own batch. The
    push is idempotent (upsert on ``(master, site)``), so re-running is safe.
    """
    from apps.sites.models import Site

    qs = Site.objects.filter(is_deleted=False)
    if site_ids is not None:
        qs = qs.filter(id__in=site_ids)
    ids = list(qs.values_list("id", flat=True))

    size = _push_batch_size()
    batches = [ids[i : i + size] for i in range(0, len(ids), size)]
    for chunk in batches:
        push_products_batch_task.delay(chunk, master_ids)
    return {"sites": len(ids), "batches": len(batches)}


@shared_task
def push_products_batch_task(site_ids, master_ids=None):
    """Push the catalog to a batch of sites, ``PRODUCT_PUSH_BATCH_SIZE`` at a time.

    Mirrors poll_sites_batch_task / apps/sites/services.check_hosting: a
    ThreadPoolExecutor caps how many sites hit the network at once, and each
    worker closes its DB connection on the way out (threads get their own
    connection). ``push_products_to_site`` swallows network errors into its
    result (never raises), so one bad site does not abort the batch.
    """
    from apps.catalog import services
    from apps.catalog.models import MasterProduct
    from apps.sites.models import Site

    sites = list(Site.objects.filter(id__in=site_ids, is_deleted=False))
    if not sites:
        return {"pushed": 0, "results": []}

    masters = None
    if master_ids is not None:
        masters = list(MasterProduct.objects.filter(id__in=master_ids))

    def _push(site):
        try:
            return services.push_products_to_site(site, masters=masters)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=_push_batch_size()) as executor:
        results = list(executor.map(_push, sites))
    return {"pushed": len(results), "results": results}
