# Ensure the Celery app is loaded when Django starts so that @shared_task
# decorators in apps/*/tasks.py register against it.
from .celery import app as celery_app

__all__ = ("celery_app",)
