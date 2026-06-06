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
        """GET /orders, paginated — used by the periodic poll to gather new orders.

        ``after`` is an ISO-8601 timestamp (the per-site watermark); only orders
        created after it are returned. Walks every page (``X-WP-TotalPages``)
        and concatenates the results. Auth is Basic; on a 401 (some shared hosts
        strip the ``Authorization`` header) it retries with the key/secret in the
        query string, per docs/backend/ARCHITECTURE.md §6.
        """
        base_params: dict = {"status": status, "per_page": min(per_page, 100)}
        if after:
            base_params["after"] = after

        orders: list[dict] = []
        page = 1
        while True:
            r = self._get_orders_page({**base_params, "page": page})
            batch = r.json()
            if not batch:
                break
            orders.extend(batch)
            total_pages = int(r.headers.get("X-WP-TotalPages", 1) or 1)
            if page >= total_pages:
                break
            page += 1
        return orders

    def _get_orders_page(self, params: dict) -> httpx.Response:
        """One page of /orders, with the query-string-auth fallback on 401."""
        r = httpx.get(f"{self.base}/orders", params=params, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = httpx.get(
                f"{self.base}/orders",
                params={**params, "consumer_key": key, "consumer_secret": secret},
                timeout=30,
            )
        r.raise_for_status()
        return r

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
