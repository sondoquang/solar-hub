"""WooClient — the single wrapper for all WooCommerce REST API traffic.

Every call to a WooCommerce site MUST go through this class (project rule).

Design notes (see tech-stack §4.4 and docs/backend/ARCHITECTURE.md):
- Per-call timeouts and ``raise_for_status()``.
- Throttle + batch endpoints when syncing many sites.
- ``consumer_secret`` is decrypted (Fernet) by the ``sites`` layer and passed in
  as plaintext here, so this class has no model dependency.
"""

import httpx


class WooClient:
    def __init__(self, base_url: str, consumer_key: str, consumer_secret: str) -> None:
        self.base = base_url.rstrip("/") + "/wp-json/wc/v3"
        self._auth = (consumer_key, consumer_secret)

    def list_orders(
        self,
        after: str | None = None,
        status: str = "processing",
        per_page: int = 100,
    ) -> list[dict]:
        raise NotImplementedError

    def batch_products(
        self,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[int] | None = None,
    ) -> dict:
        raise NotImplementedError

    def system_status(self) -> dict:
        """GET /system_status — used to verify the site's API key works."""
        r = httpx.get(f"{self.base}/system_status", auth=self._auth, timeout=15)
        r.raise_for_status()
        return r.json()
