"""Shared httpx pool for the HTTPS-based domain lookups (RDAP, Google CSE).

Same process-wide pool pattern as ``apps/integrations/woocommerce._build_pool``,
but with ``follow_redirects=True``: the rdap.org bootstrap answers with a
redirect to the authoritative registry RDAP server.
"""

import httpx
from django.conf import settings


def _build_pool() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        limits=httpx.Limits(
            max_connections=getattr(settings, "HTTP_POOL_MAX_CONNECTIONS", 100),
            max_keepalive_connections=getattr(settings, "HTTP_POOL_MAX_KEEPALIVE", 20),
            keepalive_expiry=getattr(settings, "HTTP_POOL_KEEPALIVE_EXPIRY", 30.0),
        ),
    )


# Module-level so connections are reused across lookups. Tests monkeypatch this
# object's ``get`` to intercept without network.
_POOL = _build_pool()
