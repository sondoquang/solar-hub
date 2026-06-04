from celery import shared_task


@shared_task
def check_all_sites():
    """Healthcheck each site and update Site.status. Stub for now."""
    return "noop"
