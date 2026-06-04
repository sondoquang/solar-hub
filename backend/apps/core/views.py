"""Health endpoint — proves the stack is wired (DB + Redis reachable)."""

from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.celery import app as celery_app


def _db_ok() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        return False


def _redis_ok() -> bool:
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1)
        conn.release()
        return True
    except Exception:
        return False


class HealthView(APIView):
    """GET /api/health/ → liveness (always 200) + readiness booleans.

    No authentication: a health check must not touch the DB (SessionAuth would),
    so it can still report ``db: false`` when Postgres is down instead of 500ing.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "db": _db_ok(), "redis": _redis_ok()})
