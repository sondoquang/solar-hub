"""Tests for ``RequestLogMiddleware`` — the view-layer request logger.

Driven directly with a ``RequestFactory`` request + a stub ``get_response`` so
no URL routing or DB is needed. A list handler is attached to the
``apps.request`` logger to capture the emitted line.
"""

import logging

from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.middleware import RequestLogMiddleware

from .test_logging_utils import _ListHandler


def _run(request, status: int):
    logger = logging.getLogger("apps.request")
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.addHandler(handler)
    try:
        middleware = RequestLogMiddleware(lambda req: HttpResponse(status=status))
        response = middleware(request)
    finally:
        logger.removeHandler(handler)
    return response, handler.records


def test_logs_one_line_per_request():
    request = RequestFactory().get("/api/health/")
    response, records = _run(request, 200)

    assert response.status_code == 200
    assert len(records) == 1
    message = records[0].getMessage()
    assert "request" in message
    assert "method=GET" in message
    assert "path=/api/health/" in message
    assert "status=200" in message
    assert "user=anon" in message  # unauthenticated request
    assert "dur_ms=" in message
    assert records[0].levelno == logging.INFO


def test_query_string_is_not_logged():
    # Query params can carry PII (e.g. ?email=..) — only the path is logged.
    request = RequestFactory().get("/api/orders/?customer_email=a@b.com&phone=0900")
    _, records = _run(request, 200)

    message = records[0].getMessage()
    assert "path=/api/orders/" in message
    assert "customer_email" not in message
    assert "0900" not in message


def test_server_error_logs_at_warning():
    request = RequestFactory().get("/api/dashboard/")
    _, records = _run(request, 500)

    assert records[0].levelno == logging.WARNING
    assert "status=500" in records[0].getMessage()
