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
        status: str = "processing",
        per_page: int = 100,
        after: str | None = None,
        before: str | None = None,
        modified_after: str | None = None,
    ) -> list[dict]:
        """GET /orders, paginated — used by the poll to gather orders of one status.

        ``after`` / ``before`` / ``modified_after`` are ISO-8601 timestamps. The
        periodic poll uses ``modified_after`` (the per-site watermark) so status
        transitions on older orders are caught, not just newly created ones; an
        on-demand sync over a date range uses ``after`` / ``before`` (bounds on
        ``date_created``) instead. ``dates_are_gmt`` tells Woo all bounds are GMT
        (we store the ``*_gmt`` timestamps). Walks every page
        (``X-WP-TotalPages``) and concatenates the results. Auth is Basic; on a
        401 (some shared hosts strip the ``Authorization`` header) it retries
        with the key/secret in the query string, per
        docs/backend/ARCHITECTURE.md §6.
        """
        base_params: dict = {
            "status": status,
            "per_page": min(per_page, 100),
            "dates_are_gmt": "true",
        }
        if after:
            base_params["after"] = after
        if before:
            base_params["before"] = before
        if modified_after:
            base_params["modified_after"] = modified_after

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

    def update_order(self, woo_order_id: int, *, status: str) -> dict:
        """PUT /orders/{id} — change an order's status on the site.

        Mirrors the read path: per-call timeout + ``raise_for_status()``, Basic
        auth with the query-string fallback on a 401 (some shared hosts strip
        the ``Authorization`` header). Returns the updated order payload, which
        the caller upserts so the Hub row matches the site.
        """
        url = f"{self.base}/orders/{woo_order_id}"
        payload = {"status": status}
        r = httpx.put(url, json=payload, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = httpx.put(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
                json=payload,
                timeout=30,
            )
        r.raise_for_status()
        return r.json()

    def batch_products(
        self,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[int] | None = None,
    ) -> dict:
        """POST /products/batch — create/update/delete products in one request.

        Mirrors ``update_order``: a per-call timeout (60s — batch writes are
        heavier than a read), Basic auth with the query-string fallback on a 401
        (some shared hosts strip the ``Authorization`` header), then
        ``raise_for_status()``. Returns Woo's response
        ``{"create": [...], "update": [...], "delete": [...]}`` where each item
        carries its ``id`` (the ``woo_product_id``) and ``sku``, which the caller
        matches back onto ``ProductMapping``.

        WooCommerce caps a batch at ~100 items total; the caller
        (``apps/catalog/services.push_products_to_site``) is responsible for
        chunking — this method sends whatever it is given.
        """
        url = f"{self.base}/products/batch"
        payload = {
            "create": create or [],
            "update": update or [],
            "delete": delete or [],
        }
        r = httpx.post(url, json=payload, auth=self._auth, timeout=60)
        if r.status_code == 401:
            key, secret = self._auth
            r = httpx.post(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
                json=payload,
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def system_status(self) -> dict:
        """GET /system_status — used to verify the site's API key works."""
        r = httpx.get(f"{self.base}/system_status", auth=self._auth, timeout=15)
        r.raise_for_status()
        return r.json()
