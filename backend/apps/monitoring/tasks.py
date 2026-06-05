from celery import shared_task


@shared_task
def check_all_sites():
    """Dispatch one health-check sub-task per hosting so different hostings run
    in parallel, while sites within a hosting are throttled (see check_hosting).
    Sites with no hosting are checked as their own group (``hosting_id=None``)."""
    from apps.sites.models import Hosting, Site

    hosting_ids = list(
        Hosting.objects.filter(is_deleted=False).values_list("id", flat=True)
    )
    if Site.objects.filter(hosting__isnull=True, is_deleted=False).exists():
        hosting_ids.append(None)

    for hosting_id in hosting_ids:
        check_hosting_task.delay(hosting_id)
    return {"dispatched": len(hosting_ids)}


@shared_task
def check_hosting_task(hosting_id):
    """Health-check all sites of one hosting, throttled to its check_concurrency."""
    from apps.sites import services

    return {"checked": len(services.check_hosting(hosting_id))}
