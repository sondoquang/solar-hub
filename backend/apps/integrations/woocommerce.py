"""WooClient — the single wrapper for all WooCommerce REST API traffic.

Every call to a WooCommerce site MUST go through this class (project rule).

Design notes (see tech-stack §4.4 and docs/backend/ARCHITECTURE.md):
- Per-call timeouts and ``raise_for_status()``.
- Throttle + batch endpoints when syncing many sites.
- ``consumer_secret`` is decrypted (Fernet) by the ``sites`` layer and passed in
  as plaintext here, so this class has no model dependency.
"""

import httpx
from django.conf import settings


def _build_pool() -> httpx.Client:
    """A process-wide, connection-pooled ``httpx.Client`` for all Woo traffic.

    Reusing one client keeps TCP+TLS connections alive across every page, batch
    chunk and retry (keyed per host), instead of a fresh handshake per call —
    the dominant hidden cost on high-latency shared hosts. ``httpx.Client`` is
    thread-safe, so the push/poll fan-out (ThreadPoolExecutor per batch task)
    shares this single pool. Auth/params/timeout are still passed per request
    (each site has its own key), so the 401 query-string fallback is unaffected.
    ``follow_redirects`` stays False to match the previous per-call behaviour.
    """
    return httpx.Client(
        follow_redirects=False,
        limits=httpx.Limits(
            max_connections=getattr(settings, "HTTP_POOL_MAX_CONNECTIONS", 100),
            max_keepalive_connections=getattr(settings, "HTTP_POOL_MAX_KEEPALIVE", 20),
            keepalive_expiry=getattr(settings, "HTTP_POOL_KEEPALIVE_EXPIRY", 30.0),
        ),
    )


# Module-level so connections are reused across calls AND across runs. Tests
# monkeypatch this object's ``get``/``post``/``put`` to intercept without network.
_POOL = _build_pool()


class WooClient:
    # Default per-call timeout (s) for the system_status health-check round-trip.
    # Overridable per instance so the sites layer can drive it from settings/env
    # without giving this class a settings dependency.
    DEFAULT_STATUS_TIMEOUT = 15.0

    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        status_timeout: float = DEFAULT_STATUS_TIMEOUT,
    ) -> None:
        self.base = base_url.rstrip("/") + "/wp-json/wc/v3"
        self._auth = (consumer_key, consumer_secret)
        self._status_timeout = status_timeout

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
        r = _POOL.get(f"{self.base}/orders", params=params, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.get(
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
        r = _POOL.put(url, json=payload, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.put(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
                json=payload,
                timeout=30,
            )
        r.raise_for_status()
        return r.json()

    def get_product(self, woo_id: int) -> dict:
        """GET /products/{id} — fetch one product.

        Used by the description-image sideload to learn a product's CURRENT
        gallery image ids when the product was not part of a batch this run (an
        already-synced product). Mirrors the other reads: per-call timeout, Basic
        auth with the query-string fallback on a 401 (some shared hosts strip the
        ``Authorization`` header), then ``raise_for_status()``.
        """
        url = f"{self.base}/products/{woo_id}"
        r = _POOL.get(url, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.get(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
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
        r = _POOL.post(url, json=payload, auth=self._auth, timeout=60)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.post(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
                json=payload,
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def list_categories(self, per_page: int = 100) -> list[dict]:
        """GET /products/categories, paginated — pull a site's category tree.

        Mirrors ``list_orders``: walks every page (``X-WP-TotalPages``) and
        concatenates, Basic auth with the query-string fallback on a 401 (some
        shared hosts strip the ``Authorization`` header). Returns each remote
        category dict (``{id, name, slug, parent, ...}``), which the caller
        upserts into ``Category`` / ``CategoryMapping``.
        """
        base_params = {"per_page": min(per_page, 100)}
        categories: list[dict] = []
        page = 1
        while True:
            r = self._get_categories_page({**base_params, "page": page})
            batch = r.json()
            if not batch:
                break
            categories.extend(batch)
            total_pages = int(r.headers.get("X-WP-TotalPages", 1) or 1)
            if page >= total_pages:
                break
            page += 1
        return categories

    def _get_categories_page(self, params: dict) -> httpx.Response:
        """One page of /products/categories, with the 401 query-string fallback."""
        url = f"{self.base}/products/categories"
        r = _POOL.get(url, params=params, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.get(
                url,
                params={**params, "consumer_key": key, "consumer_secret": secret},
                timeout=30,
            )
        r.raise_for_status()
        return r

    def list_products(self, per_page: int = 100, search: str | None = None) -> list[dict]:
        """GET /products, paginated — list a site's products for name matching.

        Mirrors ``list_categories``: walks every page (``X-WP-TotalPages``),
        Basic auth with the query-string fallback on a 401. ``status="any"`` so
        draft/private products are seen too (an existing draft must still be
        adopted, not duplicated). ``search`` narrows server-side when given, but
        Woo's search is fuzzy — the caller still matches by exact normalized
        name. Returns each remote product dict (``{id, name, sku, type, ...}``),
        which the caller indexes by normalized name to adopt unmapped masters.
        """
        base_params: dict = {"per_page": min(per_page, 100), "status": "any"}
        if search:
            base_params["search"] = search
        products: list[dict] = []
        page = 1
        while True:
            r = self._get_products_page({**base_params, "page": page})
            batch = r.json()
            if not batch:
                break
            products.extend(batch)
            total_pages = int(r.headers.get("X-WP-TotalPages", 1) or 1)
            if page >= total_pages:
                break
            page += 1
        return products

    def _get_products_page(self, params: dict) -> httpx.Response:
        """One page of /products, with the 401 query-string fallback."""
        url = f"{self.base}/products"
        r = _POOL.get(url, params=params, auth=self._auth, timeout=30)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.get(
                url,
                params={**params, "consumer_key": key, "consumer_secret": secret},
                timeout=30,
            )
        r.raise_for_status()
        return r

    def batch_categories(self, create: list[dict] | None = None) -> dict:
        """POST /products/categories/batch — create product categories on the site.

        Mirrors ``batch_products`` (60s timeout, Basic auth + query-string
        fallback on 401, ``raise_for_status()``). The product push uses this to
        pre-create categories not yet mapped on the site: Woo's products
        endpoint only honours ``{"id"}`` category refs — ``{"name"}`` refs are
        silently ignored (no auto-create) — so an unmapped name must become a
        site term BEFORE the product payload is built. Returns
        ``{"create": [...]}`` where each item carries ``id`` + ``name``, or an
        ``error``; a ``term_exists`` reject carries the existing term's id in
        ``error.data.resource_id``, which the caller maps instead of creating a
        duplicate. The caller chunks to the ~100-item cap.
        """
        url = f"{self.base}/products/categories/batch"
        payload = {"create": create or []}
        r = _POOL.post(url, json=payload, auth=self._auth, timeout=60)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.post(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
                json=payload,
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def batch_variations(
        self,
        parent_id: int,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[int] | None = None,
    ) -> dict:
        """POST /products/{parent_id}/variations/batch — variations in one request.

        Mirrors ``batch_products`` (60s timeout, Basic auth + query-string
        fallback on 401, ``raise_for_status()``). WooCommerce variations are child
        products of a *variable* parent, so this must run after the parent exists
        and its ``woo_product_id`` is known. Returns Woo's response
        ``{"create": [...], "update": [...], "delete": [...]}`` where each item
        carries its ``id`` (``woo_variation_id``) and ``sku``, which the caller
        matches back onto ``ProductVariationMapping``. The caller chunks to the
        ~100-item cap; this method sends whatever it is given.
        """
        url = f"{self.base}/products/{parent_id}/variations/batch"
        payload = {
            "create": create or [],
            "update": update or [],
            "delete": delete or [],
        }
        r = _POOL.post(url, json=payload, auth=self._auth, timeout=60)
        if r.status_code == 401:
            key, secret = self._auth
            r = _POOL.post(
                url,
                params={"consumer_key": key, "consumer_secret": secret},
                json=payload,
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def system_status(self) -> dict:
        """GET /system_status — used to verify the site's API key works.

        Timeout is ``status_timeout`` (constructor arg, default 15s) so the
        periodic health-check can tune it via SITE_HEALTHCHECK_TIMEOUT_SECONDS.
        """
        r = _POOL.get(f"{self.base}/system_status", auth=self._auth, timeout=self._status_timeout)
        r.raise_for_status()
        return r.json()
