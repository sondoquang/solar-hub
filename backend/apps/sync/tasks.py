from celery import shared_task


@shared_task
def poll_all_orders():
    """Fallback poll of new orders across all sites. Stub for now."""
    return "noop"
