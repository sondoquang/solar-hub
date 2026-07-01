import uuid
from concurrent.futures import ThreadPoolExecutor

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import connection

_PULL_CATEGORIES_LOCK_KEY = "lock:pull_all_categories"
_PULL_CATEGORIES_LOCK_TTL = 600  # 10 min — expected max run time across all sites


def _batch_size() -> int:
    """Sites polled concurrently per batch task (settings, default 8, min 1)."""
    return max(1, getattr(settings, "ORDER_POLL_BATCH_SIZE", 8))


def _push_batch_size() -> int:
    """Sites pushed concurrently per batch task (settings, default 8, min 1)."""
    return max(1, getattr(settings, "PRODUCT_PUSH_BATCH_SIZE", 8))


@shared_task
def poll_all_orders(
    status=None,
    site_ids=None,
    date_from=None,
    date_to=None,
    run_id=None,
    triggered_by_id=None,
    platform=None,
):
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

    ``run_id`` (set by the "Đồng bộ ngay" view) groups this fan-out's per-site
    ``SyncLog`` rows so the progress banner can poll completion; it is None for
    the periodic beat, which then writes no SyncLog rows (a row every ~3 min per
    site would bloat the audit table for no report). ``triggered_by_id`` is the
    admin who clicked sync, threaded onto each row.
    """
    from apps.orders.services import POLL_STATUS, sites_for_order_poll

    status = status or POLL_STATUS

    # WooCommerce sites are polled individually; Sapo sites are gated by
    # SAPO_ORDER_POLL_ENABLED and deduplicated by store (several storefront
    # domains can share one Sapo backend). ``platform`` (set by the per-platform
    # "Đồng bộ ngay" screens) restricts the run to one platform. See
    # sites_for_order_poll.
    ids = sites_for_order_poll(site_ids, platform=platform)

    size = _batch_size()
    batches = [ids[i : i + size] for i in range(0, len(ids), size)]
    for chunk in batches:
        poll_sites_batch_task.delay(
            chunk, status, date_from, date_to, run_id=run_id, triggered_by_id=triggered_by_id
        )
    return {"status": status, "sites": len(ids), "batches": len(batches), "run_id": run_id}


@shared_task
def poll_sites_batch_task(
    site_ids, status, date_from=None, date_to=None, run_id=None, triggered_by_id=None
):
    """Poll one status for a batch of sites, ``ORDER_POLL_BATCH_SIZE`` at a time.

    Mirrors apps/sites/services.check_hosting: a ThreadPoolExecutor caps how
    many sites hit the network at once. ``poll_site`` swallows network errors
    into its result (never raises), so one bad site does not abort the batch.
    ``run_id``/``triggered_by_id`` are threaded to ``poll_site`` so each site's
    outcome is logged for the progress banner (manual runs only).
    """
    from apps.orders import services
    from apps.sites.models import Site

    sites = list(Site.objects.filter(id__in=site_ids, is_deleted=False))
    if not sites:
        return {"status": status, "polled": 0, "results": []}

    def _poll(site):
        try:
            return services.poll_site(
                site,
                status,
                date_from=date_from,
                date_to=date_to,
                run_id=run_id,
                triggered_by_id=triggered_by_id,
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=_batch_size()) as executor:
        results = list(executor.map(_poll, sites))
    return {"status": status, "polled": len(results), "results": results}


@shared_task
def push_all_products(site_ids=None, master_ids=None, run_id=None, triggered_by_id=None):
    """Push the catalog to sites, split into concurrent batches ("Sync all").

    The "Đồng bộ ngay" UI (or admin action) triggers this. ``site_ids`` scopes
    which sites to push to (all live sites when omitted); ``master_ids`` scopes
    which products (the whole catalog when omitted). The target set runs through
    ``sites_for_product_push`` so a Sapo store reachable under several storefront
    domains is pushed once, not once per domain. Sites are chunked into batches
    of ``PRODUCT_PUSH_BATCH_SIZE`` and one ``push_products_batch_task`` is
    dispatched per chunk, so a slow/broken site only holds up its own batch. The
    push is idempotent (upsert on ``(master, site)``), so re-running is safe.

    ``run_id`` (set by the "Đồng bộ ngay" view) groups this fan-out's per-site
    ``SyncLog`` rows so the progress banner can poll completion; ``triggered_by_id``
    is the admin who clicked sync. Both are threaded onto each row.
    """
    from apps.sites.services import sites_for_product_push

    ids = sites_for_product_push(site_ids)

    size = _push_batch_size()
    batches = [ids[i : i + size] for i in range(0, len(ids), size)]
    for chunk in batches:
        push_products_batch_task.delay(
            chunk, master_ids, run_id=run_id, triggered_by_id=triggered_by_id
        )
    return {"sites": len(ids), "batches": len(batches), "run_id": run_id}


@shared_task
def push_products_batch_task(site_ids, master_ids=None, run_id=None, triggered_by_id=None):
    """Push the catalog to a batch of sites, ``PRODUCT_PUSH_BATCH_SIZE`` at a time.

    Mirrors poll_sites_batch_task / apps/sites/services.check_hosting: a
    ThreadPoolExecutor caps how many sites hit the network at once, and each
    worker closes its DB connection on the way out (threads get their own
    connection). ``push_products_to_site`` swallows network errors into its
    result (never raises), so one bad site does not abort the batch.
    ``run_id``/``triggered_by_id`` are threaded onto each site's ``SyncLog`` row
    for the progress banner.
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
            return services.push_products_to_site(
                site, masters=masters, run_id=run_id, triggered_by_id=triggered_by_id
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=_push_batch_size()) as executor:
        results = list(executor.map(_push, sites))
    return {"pushed": len(results), "results": results}


@shared_task
def pull_all_categories(site_ids=None, run_id=None, triggered_by_id=None):
    """Pull product categories from sites into the Hub, in concurrent batches.

    Mirrors ``poll_all_orders``: live sites are chunked into batches of
    ``ORDER_POLL_BATCH_SIZE`` and one ``pull_categories_batch_task`` is dispatched
    per chunk, so a slow/broken site only holds up its own batch. The pull is
    idempotent (upsert on ``(site, woo_category_id)``), so re-running is safe.

    ``run_id`` groups every per-site ``SyncLog`` row of this fan-out (one user
    click = one run, the unit of the category-run report). The view generates
    it so the API can return it; generated here when absent (shell/beat calls).
    ``triggered_by_id`` is the admin who clicked sync (threaded onto each
    SyncLog for the "Người chạy" column); null for periodic/beat runs.

    A full-site run (``site_ids=None``) acquires a Redis cache lock for
    ``_PULL_CATEGORIES_LOCK_TTL`` seconds so rapid re-triggers (user clicking
    "sync" repeatedly) dispatch only one set of batch tasks. Scoped runs
    (``site_ids`` set) bypass the lock and can overlap freely.
    """
    if site_ids is None and not cache.add(
        _PULL_CATEGORIES_LOCK_KEY, "1", timeout=_PULL_CATEGORIES_LOCK_TTL
    ):
        return {"status": "skipped_already_running", "sites": 0, "batches": 0}

    from apps.sites.models import Site

    if run_id is None:
        run_id = str(uuid.uuid4())

    qs = Site.objects.filter(is_deleted=False)
    if site_ids is not None:
        qs = qs.filter(id__in=site_ids)
    ids = list(qs.values_list("id", flat=True))

    size = _batch_size()
    batches = [ids[i : i + size] for i in range(0, len(ids), size)]
    for chunk in batches:
        pull_categories_batch_task.delay(chunk, run_id=run_id, triggered_by_id=triggered_by_id)
    return {"sites": len(ids), "batches": len(batches), "run_id": run_id}


@shared_task
def pull_categories_batch_task(site_ids, run_id=None, triggered_by_id=None):
    """Pull categories for a batch of sites, ``ORDER_POLL_BATCH_SIZE`` at a time.

    Mirrors poll_sites_batch_task: a ThreadPoolExecutor caps how many sites hit
    the network at once, and each worker closes its DB connection on the way out.
    ``pull_categories_for_site`` swallows network errors into its result (never
    raises), so one bad site does not abort the batch.
    """
    from apps.catalog import services
    from apps.sites.models import Site

    sites = list(Site.objects.filter(id__in=site_ids, is_deleted=False))
    if not sites:
        return {"pulled": 0, "results": []}

    def _pull(site):
        try:
            return services.pull_categories_for_site(
                site, run_id=run_id, triggered_by_id=triggered_by_id
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=_batch_size()) as executor:
        results = list(executor.map(_pull, sites))
    return {"pulled": len(results), "results": results}


_IMPORT_PRODUCTS_LOCK_TTL = 600  # 10 min — expected max import time for one site


@shared_task
def import_products_task(site_id, run_id=None, triggered_by_id=None):
    """Import one site's products into the Hub catalog (the "Nhập từ website chính").

    Unlike the push/pull fan-outs this targets a SINGLE site — importing the same
    products from many sites would create conflicting masters — so there is no
    batch split. A per-site Redis lock (``lock:import_products:{id}``) makes a
    rapid double-click dispatch only one import. ``run_id`` groups the site's
    ``SyncLog`` row so the progress banner (expected=1) can poll completion;
    ``triggered_by_id`` is the admin who clicked import. Network errors are
    swallowed by ``import_products_from_site`` into a SyncLog row, never raised.
    """
    lock_key = f"lock:import_products:{site_id}"
    if not cache.add(lock_key, "1", timeout=_IMPORT_PRODUCTS_LOCK_TTL):
        return {"status": "skipped_already_running", "site_id": site_id}

    from apps.catalog import services
    from apps.sites.models import Site

    if run_id is None:
        run_id = str(uuid.uuid4())

    try:
        site = Site.objects.filter(id=site_id, is_deleted=False).first()
        if site is None:
            return {"status": "site_not_found", "site_id": site_id}
        return services.import_products_from_site(
            site, run_id=run_id, triggered_by_id=triggered_by_id
        )
    finally:
        cache.delete(lock_key)
        connection.close()
