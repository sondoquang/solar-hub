"""Request-level logging — covers the whole view layer from one place.

``RequestLogMiddleware`` emits exactly one line per HTTP request (after the view
runs), through the ``apps.request`` logger. This is how the "view layer" gets
per-request logging without editing every DRF view/action.

No PII (CLAUDE.md #4): we log method, path, status, the acting user *id*, and the
duration — never the query string or body (those can carry customer data).
"""

import logging
import time

from .logging_utils import log_event

logger = logging.getLogger("apps.request")


class RequestLogMiddleware:
    """Log ``request method=.. path=.. status=.. user=.. dur_ms=..`` per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        duration_ms = int((time.perf_counter() - started) * 1000)

        # WARNING for 5xx, INFO otherwise — 5xx also lands in error.log.
        status = getattr(response, "status_code", 0)
        level = logging.WARNING if status >= 500 else logging.INFO

        log_event(
            logger,
            level,
            "request",
            method=request.method,
            path=request.path,  # path only — never the query string (may hold PII)
            status=status,
            user=self._user_id(request),
            dur_ms=duration_ms,
        )
        return response

    @staticmethod
    def _user_id(request):
        """Acting user's id, or ``"anon"`` — never the username/email (PII)."""
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return user.id
        return "anon"
