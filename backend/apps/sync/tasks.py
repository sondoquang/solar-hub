from celery import shared_task


@shared_task
def poll_all_orders():
    """Fallback poll of new orders across all sites (Celery Beat, every ~3 min).

    Fans out one ``poll_site_task`` per site so a slow/broken site does not hold
    up the others (mirrors apps/monitoring/tasks.check_all_sites). The upsert is
    idempotent, so overlap with a future webhook is safe.
    """
    from apps.sites.models import Site

    site_ids = list(
        Site.objects.filter(is_deleted=False).values_list("id", flat=True)
    )
    for site_id in site_ids:
        poll_site_task.delay(site_id)
    return {"dispatched": len(site_ids)}


@shared_task(bind=True, max_retries=3, default_retry_backoff=True)
def poll_site_task(self, site_id):
    """Poll one site's new orders. Retries with backoff on network errors."""
    from apps.orders import services
    from apps.sites.models import Site

    site = Site.objects.filter(id=site_id, is_deleted=False).first()
    if site is None:
        return {"site_id": site_id, "error": "not_found"}

    result = services.poll_site(site)
    # poll_site swallows httpx errors into ``error``; retry the transient ones.
    if result.get("error"):
        raise self.retry(exc=Exception(result["error"]))
    return result
