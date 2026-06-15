"""SapoClient — Woo-shaped adapter over the Sapo Web admin API.

Sapo Web (Shopify-like) exposes per-store REST endpoints at
``https://{store-domain}/admin/*.json``, authenticated with a private app's
API key/secret via Basic auth. This class exposes the SAME method surface as
``WooClient`` — it accepts WooCommerce-shaped payloads (what
``apps/catalog/services.build_product_payload`` produces) and returns
WooCommerce-shaped responses, so the catalog push flow runs unchanged on Sapo
sites. ``client_for_site`` (apps/sites/services.py) picks the class by
``Site.platform``.

Key platform differences absorbed here:
- No batch endpoints: one Woo "batch" becomes sequential per-product requests,
  paced by ``throttle_seconds`` with 429/Retry-After retries.
- SKU/price/stock live on *variants* (a simple product is one default variant).
- A variable product carries ``options`` (max 3) and needs >= 1 variant to
  materialize them — created with a placeholder variant that the first real
  variation overwrites in place (avoids a duplicate-option-combo 422).
- Categories are flat *custom collections*; product↔collection links are
  separate ``Collect`` objects, synced best-effort after each product write.
- ``grouped``/``external`` products do not exist on Sapo → per-item error
  (``sapo_unsupported_type``) so the push reports PARTIAL instead of failing.
- A PUT/GET of a product deleted on the site returns 404, which is mapped to
  the ``woocommerce_rest_product_invalid_id`` error code so the service's
  existing stale-mapping recovery re-creates the product without changes.

Orders: ``list_orders`` maps Sapo orders (GET /admin/orders.json) to the same
WooCommerce shape the orders service expects, so the periodic poll and the
classification flow run unchanged on Sapo sites. ``update_order`` pushes a
status change via Sapo's close/cancel endpoints (Sapo has no generic order
``status`` field). Sapo status (open/closed/cancelled) maps 1:1 to the Woo
status the Hub stores (processing/completed/cancelled). Unlike Woo, the Sapo
order flow tracks payment: ``financial_status`` is carried through to the Hub
(``Order.payment_status``), ``list_orders`` can filter by it (``financial_status``
param — the poll passes ``"unpaid"``), and ``mark_order_paid`` records a full
``sale`` transaction (Sapo has no settable payment-status field). Fulfillment
status is still ignored.
"""

import logging
import re
import time
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

# A datetime string already carrying a timezone: ends with ``Z`` or a ``±HH:MM``
# (or ``±HHMM``) offset. Used to decide whether a Sapo date filter needs a tz
# stamped on — see ``_with_tz``.
_HAS_TZ_RE = re.compile(r"(Z|[+-]\d\d:?\d\d)$")

# Sapo paginates at 250 items max per page (Shopify-style).
_PAGE_LIMIT = 250
# Hard backstop for order paging (250 * 2000 = 500k orders) so a misbehaving
# endpoint that never returns a short page cannot loop forever.
_MAX_ORDER_PAGES = 2000
# A product belongs to at most 3 options (option1..option3).
MAX_OPTIONS = 3

# The admin REST API only answers on the store's canonical Sapo host; a custom
# storefront domain (what users usually register as base_url) 302-redirects
# /admin/*.json there. We follow that redirect ourselves — httpx drops Basic
# auth across hosts and downgrades a 302'd POST to GET — but only toward a Sapo
# host (or the same host), so credentials are never replayed to a foreign domain.
_SAPO_ADMIN_HOST_SUFFIX = ".mysapo.net"
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 3

_INVALID_ID_ERROR = {
    "code": "woocommerce_rest_product_invalid_id",
    "message": "Sản phẩm không còn tồn tại trên Sapo.",
}


def _to_number(value):
    """Woo payloads carry prices/weights as strings ('' = unset) — Sapo wants
    numbers. Returns float or None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_fields(regular, sale) -> dict:
    """Woo regular/sale price → Sapo price/compare_at_price.

    Sapo's ``price`` is the actual selling price and ``compare_at_price`` the
    strikethrough original — so an active sale maps to price=sale,
    compare_at_price=regular; no sale maps to price=regular, compare cleared.
    """
    reg = _to_number(regular)
    sal = _to_number(sale)
    if sal is not None:
        return {"price": sal, "compare_at_price": reg}
    return {"price": reg if reg is not None else 0, "compare_at_price": None}


def _inventory_fields(stock_status) -> dict:
    """Woo stock_status → Sapo inventory tracking (v1: no quantities on the Hub).

    instock → untracked (always purchasable); outofstock → tracked at 0, deny;
    onbackorder → tracked at 0 but oversellable (policy continue).
    """
    if stock_status == "outofstock":
        return {"inventory_management": "sapo", "inventory_quantity": 0, "inventory_policy": "deny"}
    if stock_status == "onbackorder":
        return {
            "inventory_management": "sapo",
            "inventory_quantity": 0,
            "inventory_policy": "continue",
        }
    return {"inventory_management": None}


def _weight_fields(weight) -> dict:
    """Woo weight (kg, string) → Sapo weight/weight_unit; omitted when unset
    (Sapo has no documented 'clear weight' semantics, unlike Woo's '')."""
    value = _to_number(weight)
    if value is None:
        return {}
    return {"weight": value, "weight_unit": "kg"}


def _publish_fields(status) -> dict:
    """Woo status → Sapo publish flag. Only ``publish`` goes live; draft/
    pending/private stay unpublished (Sapo has no finer-grained states)."""
    if status == "publish":
        return {"published_on": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {"published_on": None}


def _default_variant(item: dict) -> dict:
    """The single variant of a simple product — carrier of sku/price/stock."""
    return {
        "sku": item.get("sku", ""),
        **_price_fields(item.get("regular_price"), item.get("sale_price")),
        **_inventory_fields(item.get("stock_status")),
        **_weight_fields(item.get("weight")),
    }


def _variation_attributes(item: dict) -> list[dict]:
    """The attributes of a Woo payload that define variations (→ Sapo options)."""
    return [a for a in item.get("attributes") or [] if a.get("variation")]


def _variable_options(item: dict) -> tuple[list[dict], dict]:
    """Options + placeholder variant for creating a variable product.

    Sapo (like Shopify) only materializes ``options`` when at least one variant
    exists, so the create ships a placeholder combining the FIRST value of each
    option, with an empty sku — ``batch_variations`` later overwrites it in
    place with the first real variation (real variations always carry SKUs).
    """
    attrs = _variation_attributes(item)
    options = [{"name": a.get("name", "")} for a in attrs]
    placeholder = {"sku": "", "price": 0, "inventory_management": None}
    for i, a in enumerate(attrs[:MAX_OPTIONS], start=1):
        values = a.get("options") or [""]
        placeholder[f"option{i}"] = values[0]
    return options, placeholder


def _woo_product_to_sapo(item: dict) -> dict:
    """Product-level fields of a Woo payload → Sapo product fields (no
    variants/options — the callers add those per product type)."""
    return {
        "name": item.get("name", ""),
        "content": item.get("description", ""),
        "summary": item.get("short_description", ""),
        **_publish_fields(item.get("status")),
        "images": [
            {"src": img.get("src"), "position": i + 1}
            for i, img in enumerate(item.get("images") or [])
            if img.get("src")
        ],
    }


def _woo_variation_to_sapo(item: dict, option_names: list[str]) -> tuple[dict, list[str]]:
    """A Woo variation payload → Sapo variant dict.

    Woo variation attributes are ``[{"name", "option"}]``; Sapo wants them as
    ``option1..option3`` positioned by the PARENT's options order. Returns the
    variant plus the attribute names that did not match any parent option
    (non-empty → the caller rejects the item as ``sapo_option_mismatch``).
    """
    variant = {
        "sku": item.get("sku", ""),
        **_price_fields(item.get("regular_price"), item.get("sale_price")),
        **_inventory_fields(item.get("stock_status")),
        **_weight_fields(item.get("weight")),
    }
    by_name = {a.get("name"): a.get("option") for a in item.get("attributes") or []}
    for i, name in enumerate(option_names[:MAX_OPTIONS], start=1):
        if name in by_name:
            variant[f"option{i}"] = by_name.pop(name)
    return variant, sorted(n for n in by_name if n)


def _guard_item(item: dict) -> dict | None:
    """Per-item error for masters Sapo cannot represent, or None when pushable.

    Returned through the batch response so ``_collect_batch_failures`` records
    it in ``SyncLog.detail.failed`` (status PARTIAL) — same path as a Woo
    per-item reject. These items never gain a mapping and are re-reported on
    every push, which keeps the gap visible in the sync report.
    """
    ptype = item.get("type")
    if ptype in ("grouped", "external"):
        return {
            "code": "sapo_unsupported_type",
            "message": f"Sapo không hỗ trợ sản phẩm loại '{ptype}'.",
        }
    if ptype == "variable" and len(_variation_attributes(item)) > MAX_OPTIONS:
        return {
            "code": "sapo_max_options_exceeded",
            "message": f"Sapo chỉ hỗ trợ tối đa {MAX_OPTIONS} thuộc tính biến thể.",
        }
    return None


def _normalize_title(name: str) -> str:
    """Collection-name key for duplicate detection (Sapo accepts duplicate
    names, unlike Woo's term_exists) — trim, collapse spaces, casefold."""
    return " ".join((name or "").split()).casefold()


# --- orders ------------------------------------------------------------------
#
# Sapo's order lifecycle is only open/closed/cancelled (financial_status and
# fulfillment_status are separate and ignored in v1), so each Sapo order maps to
# exactly ONE Woo status the Hub stores — which keeps the per-(site, status)
# poll watermark from ever double-counting an order. The reverse map turns a
# requested Woo status into the Sapo ``status`` query param; a Woo status Sapo
# has no equivalent for is simply absent (the poll then fetches nothing).
_SAPO_TO_WOO_STATUS = {
    "open": "processing",
    "closed": "completed",
    "cancelled": "cancelled",
}
_WOO_TO_SAPO_STATUS = {woo: sapo for sapo, woo in _SAPO_TO_WOO_STATUS.items()}

# A target Woo status → the Sapo endpoint action that reaches it. Sapo has no
# generic status field: completing an order archives it (close), cancelling
# hits a dedicated cancel endpoint. Other transitions are unsupported.
_SAPO_STATUS_ACTIONS = {"completed": "close", "cancelled": "cancel"}

# Sapo's ``financial_status`` query matches a SINGLE literal payment status — it
# has no Shopify-style ``unpaid`` group alias and rejects comma-separated lists
# (both verified to return zero orders against a live store). The Hub's poll asks
# for the unpaid *group*, so ``list_orders`` expands this sentinel into one query
# per literal status and merges. Mirrors apps.orders.services.UNPAID_PAYMENT_STATUSES.
_UNPAID_GROUP = "unpaid"
_UNPAID_FINANCIAL_STATUSES = ("pending", "authorized", "partially_paid")


def _with_tz(value: str | None) -> str | None:
    """Stamp a UTC ``Z`` onto a timezone-naive datetime filter value.

    Sapo's ``created_on_*`` / ``modified_on_*`` filters SILENTLY IGNORE a
    timezone-naive datetime (verified against a live store: ``...T00:00:00`` is
    dropped, ``...T00:00:00Z`` is honored) — so a naive bound makes the poll
    fetch *every* order instead of the requested window. The orders service
    builds naive GMT bounds (``apps.orders.services._date_bounds``) and a
    watermark that may also be naive; treat any value lacking a timezone as UTC.
    Values that already carry one (``+00:00`` from an aware watermark) pass
    through unchanged.
    """
    if not value or _HAS_TZ_RE.search(value):
        return value
    return value + "Z"


def _woo_address(addr: dict | None) -> dict:
    """A Sapo address dict → the WooCommerce billing/shipping shape that
    ``apps.orders.services.normalize_order`` reads (``address_1``/``state``/
    ``postcode`` vs Sapo's ``address1``/``province``/``zip``)."""
    addr = addr or {}
    return {
        "first_name": addr.get("first_name", ""),
        "last_name": addr.get("last_name", ""),
        "phone": addr.get("phone", ""),
        "address_1": addr.get("address1", ""),
        "address_2": addr.get("address2", ""),
        "city": addr.get("city", ""),
        "state": addr.get("province", ""),
        "postcode": addr.get("zip", ""),
        "country": addr.get("country", ""),
    }


def _woo_line_items(items: list | None) -> list[dict]:
    """Sapo line items → the trimmed Woo shape (sku/name/quantity/total). Sapo
    carries a unit ``price``; the Hub stores a line ``total``, so fall back to
    ``price * quantity`` when Sapo sends no explicit line total."""
    out = []
    for it in items or []:
        qty = it.get("quantity") or 0
        line_total = it.get("line_price")
        if line_total is None:
            line_total = (_to_number(it.get("price")) or 0) * qty
        out.append(
            {
                "sku": it.get("sku", ""),
                "name": it.get("title") or it.get("name", ""),
                "quantity": qty,
                "total": str(line_total),
            }
        )
    return out


def _sapo_order_to_woo(order: dict | None) -> dict:
    """One Sapo order → a WooCommerce-shaped order dict.

    Lets ``apps.orders.services`` (normalize → upsert → classify) consume a
    Sapo order with no Sapo-specific branch. Only the fields the Hub stores are
    mapped. Email/phone/name are backfilled from the ``customer`` object when
    the billing address omits them, so the spam classifier still sees them.
    ``created_on``/``modified_on`` are ISO-8601 (``parse_datetime`` reads them).
    """
    order = order or {}
    customer = order.get("customer") or {}
    billing = _woo_address(order.get("billing_address"))
    billing["email"] = order.get("email") or customer.get("email") or ""
    if not billing["phone"]:
        billing["phone"] = customer.get("phone", "")
    if not (billing["first_name"] or billing["last_name"]):
        billing["first_name"] = customer.get("first_name", "")
        billing["last_name"] = customer.get("last_name", "")
    return {
        "id": order.get("id"),
        "number": str(
            order.get("name") or order.get("order_number") or order.get("id") or ""
        ),
        "status": _SAPO_TO_WOO_STATUS.get(order.get("status"), order.get("status") or ""),
        "currency": order.get("currency", ""),
        "total": order.get("total_price") or 0,
        "billing": billing,
        "shipping": _woo_address(order.get("shipping_address")),
        "customer_note": order.get("note") or "",
        "line_items": _woo_line_items(order.get("line_items")),
        "date_created_gmt": order.get("created_on"),
        "date_modified_gmt": order.get("modified_on"),
        # Sapo payment status (pending/authorized/partially_paid/paid/…). The
        # orders service stores it as ``Order.payment_status``; the Sapo order
        # flow drives off it rather than the lifecycle ``status``.
        "financial_status": order.get("financial_status") or "",
    }


class SapoClient:
    # Default per-call timeout (s) for the store.json health-check round-trip;
    # overridable per instance, mirroring WooClient.
    DEFAULT_STATUS_TIMEOUT = 15.0

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        status_timeout: float = DEFAULT_STATUS_TIMEOUT,
        throttle_seconds: float = 0.5,
        max_429_retries: int = 5,
        retry_after_default: float = 2.0,
    ) -> None:
        self.base = base_url.rstrip("/") + "/admin"
        self._auth = (api_key, api_secret)
        self._status_timeout = status_timeout
        self._throttle = throttle_seconds
        self._max_429_retries = max_429_retries
        self._retry_after_default = retry_after_default
        self._last_request_at = 0.0
        # The canonical host the last request actually landed on (after any
        # redirect to ``*.mysapo.net``). The sites layer persists this on the
        # Site so the order poll can dedupe storefront domains that share one
        # Sapo store. None until the first request.
        self.resolved_host: str | None = None

    # ------------------------------------------------------------------ http

    def _request(self, method: str, path: str, *, json=None, params=None, timeout=30.0):
        """One paced request. Raises on network errors, 5xx and exhausted 429
        retries (all ``httpx.HTTPError`` — caught per-site by the services);
        other 4xx responses are RETURNED so callers map them to per-item
        errors instead of failing the whole site."""
        url = f"{self.base}{path}"
        r = None
        for attempt in range(self._max_429_retries + 1):
            self._pace()
            r = self._send(method, url, json=json, params=params, timeout=timeout)
            self._last_request_at = time.monotonic()
            if r.status_code != 429:
                break
            if attempt >= self._max_429_retries:
                break
            time.sleep(self._retry_after_seconds(r))
        if r.status_code == 429 or r.status_code >= 500:
            r.raise_for_status()
        return r

    def _send(self, method, url, *, json, params, timeout, _redirects=_MAX_REDIRECTS):
        """One HTTP call that manually follows a redirect to the canonical Sapo
        admin host, re-applying Basic auth and keeping the method/body (httpx
        strips the auth header cross-host and turns a 302'd POST into a GET).
        Only follows toward a ``*.mysapo.net`` or same host — see the module
        constants — so credentials never reach an unrelated redirect target."""
        r = httpx.request(method, url, json=json, params=params, auth=self._auth, timeout=timeout)
        if _redirects > 0 and r.status_code in _REDIRECT_CODES:
            location = r.headers.get("Location")
            if location:
                origin = httpx.URL(url)
                target = origin.join(location)  # absolute Location returns as-is
                if self._auth_safe_redirect(origin, target):
                    # the redirect target already carries the query string
                    return self._send(
                        method, str(target), json=json, params=None,
                        timeout=timeout, _redirects=_redirects - 1,
                    )
        # Terminal response (no further redirect followed): record the host we
        # actually landed on so the sites layer can persist the store identity.
        self.resolved_host = httpx.URL(url).host
        return r

    @staticmethod
    def _auth_safe_redirect(origin, target) -> bool:
        host = (target.host or "").lower()
        return host == (origin.host or "").lower() or host.endswith(_SAPO_ADMIN_HOST_SUFFIX)

    def _pace(self) -> None:
        if not self._throttle:
            return
        wait = self._throttle - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _retry_after_seconds(self, r) -> float:
        try:
            return max(float(r.headers.get("Retry-After")), 0.0)
        except (TypeError, ValueError):
            return self._retry_after_default

    @staticmethod
    def _http_error(r) -> dict:
        """A non-OK Sapo response as a Woo-shaped per-item error (no payload
        echo beyond Sapo's own error body, truncated)."""
        try:
            message = str(r.json().get("errors", ""))[:300]
        except Exception:
            message = (r.text or "")[:300]
        return {"code": f"sapo_http_{r.status_code}", "message": message}

    # ----------------------------------------------------------------- orders

    def list_orders(
        self,
        status: str = "processing",
        per_page: int = 100,
        after: str | None = None,
        before: str | None = None,
        modified_after: str | None = None,
        financial_status: str | None = None,
    ) -> list[dict]:
        """GET /admin/orders.json, paginated — Woo-shaped orders for the poll.

        Same signature/semantics as ``WooClient.list_orders``: the periodic
        poll passes the per-site watermark as ``modified_after`` (→ Sapo
        ``modified_on_min``) so status transitions on older orders are caught,
        not just new ones; an on-demand date-range sync passes ``after`` /
        ``before`` (→ ``created_on_min`` / ``created_on_max``) instead. The
        requested *Woo* status is mapped to Sapo's ``status`` query param; a Woo
        status Sapo has no equivalent for (pending/on-hold/refunded/failed)
        yields an empty list rather than a bad query.

        Paginates with ``page`` + ``limit`` (Sapo honors ``page`` and returns
        orders newest-first), stopping on a short/empty page. ``_MAX_ORDER_PAGES``
        is a hard backstop so a misbehaving endpoint that keeps returning a full
        page can never loop forever (logged if hit). ``raise_for_status`` lets a
        4xx (e.g. a bad key) surface as the ``httpx.HTTPError`` the per-site poll
        catches.

        ``financial_status`` (Sapo-only; WooClient has no such param) layers a
        payment-status filter onto the query — the orders service passes
        ``"unpaid"`` for Sapo sites so the poll fetches only orders not yet paid
        (``status="processing"`` → Sapo ``open`` keeps the per-(site, status)
        watermark single-valued; see apps.orders.services.poll_site). Sapo has no
        ``unpaid`` group alias, so that sentinel is expanded into one paginated
        query per literal unpaid status (``_UNPAID_FINANCIAL_STATUSES``), merged
        and deduped by id; any other value is passed through as a single literal.
        """
        sapo_status = _WOO_TO_SAPO_STATUS.get(status)
        if sapo_status is None:
            return []
        limit = min(per_page, _PAGE_LIMIT)
        params: dict = {"status": sapo_status, "limit": limit}
        # Sapo ignores a timezone-naive date filter (see _with_tz) — stamp UTC.
        if after:
            params["created_on_min"] = _with_tz(after)
        if before:
            params["created_on_max"] = _with_tz(before)
        if modified_after:
            params["modified_on_min"] = _with_tz(modified_after)

        if financial_status == _UNPAID_GROUP:
            # One query per literal status (Sapo can't OR them); dedup by id is
            # defensive — an order has exactly one financial_status, so the sets
            # never overlap across statuses.
            by_id: dict = {}
            for fs in _UNPAID_FINANCIAL_STATUSES:
                for o in self._paginate_orders({**params, "financial_status": fs}, limit):
                    by_id[o.get("id")] = o
            orders = list(by_id.values())
        elif financial_status:
            orders = self._paginate_orders({**params, "financial_status": financial_status}, limit)
        else:
            orders = self._paginate_orders(params, limit)

        return [_sapo_order_to_woo(o) for o in orders]

    def _paginate_orders(self, params: dict, limit: int) -> list[dict]:
        """GET /admin/orders.json across pages for one filter set (raw Sapo
        orders). Stops on a short/empty page; ``_MAX_ORDER_PAGES`` backstops a
        misbehaving endpoint that never shortens (logged if hit)."""
        orders: list[dict] = []
        for page in range(1, _MAX_ORDER_PAGES + 1):
            r = self._request("GET", "/orders.json", params={**params, "page": page})
            r.raise_for_status()
            batch = r.json().get("orders") or []
            orders.extend(batch)
            if len(batch) < limit:
                break
        else:
            logger.warning(
                "list_orders hit the %s-page cap (status=%s, financial_status=%s) — "
                "results truncated",
                _MAX_ORDER_PAGES,
                params.get("status"),
                params.get("financial_status"),
            )
        return orders

    def update_order(self, woo_order_id: int, *, status: str) -> dict:
        """Push a status change to Sapo, returning the Woo-shaped order.

        Mirrors ``WooClient.update_order`` (the orders service calls it, then
        upserts the returned payload so the Hub row matches the site). Sapo has
        no generic status field: ``completed`` archives the order (POST
        ``/orders/{id}/close.json``) and ``cancelled`` cancels it (POST
        ``/orders/{id}/cancel.json``); any other target raises. The endpoint
        returns the updated order, mapped back so the advanced ``modified_on``
        keeps the next poll from reverting it. ``raise_for_status`` lets a
        non-2xx propagate as the ``httpx.HTTPError`` the service maps to a 502.
        """
        action = _SAPO_STATUS_ACTIONS.get(status)
        if action is None:
            raise NotImplementedError(
                f"Sapo chỉ hỗ trợ hoàn thành/hủy đơn, không chuyển sang '{status}'."
            )
        r = self._request(
            "POST", f"/orders/{woo_order_id}/{action}.json", json={}, timeout=60
        )
        r.raise_for_status()
        return _sapo_order_to_woo(r.json().get("order") or {})

    def get_order(self, woo_order_id: int) -> dict:
        """GET /admin/orders/{id}.json → the single order, Woo-shaped.

        Used to re-read an order after a write whose response is not the order
        itself (e.g. ``mark_order_paid`` returns a transaction). ``raise_for_status``
        lets a non-2xx propagate as the ``httpx.HTTPError`` the service maps to a 502.
        """
        r = self._request("GET", f"/orders/{woo_order_id}.json", timeout=60)
        r.raise_for_status()
        return _sapo_order_to_woo(r.json().get("order") or {})

    def mark_order_paid(self, woo_order_id: int, *, amount) -> dict:
        """Mark a Sapo order paid by recording a full ``sale`` transaction.

        Sapo (Shopify-like) has no settable ``financial_status`` field: paying an
        order means POSTing a transaction. ``kind="sale"`` authorizes+captures in
        one step for the full ``amount`` (the order total); ``source_name="web"``
        marks it as recorded from the Hub. The transactions endpoint returns the
        *transaction*, not the order, so we re-GET the order to read the updated
        ``financial_status`` and return it Woo-shaped (the service upserts it so
        the Hub row matches the site). Sapo-only — ``WooClient`` has no equivalent;
        ``raise_for_status`` lets a non-2xx propagate as ``httpx.HTTPError``.
        """
        r = self._request(
            "POST",
            f"/orders/{woo_order_id}/transactions.json",
            json={
                "transaction": {
                    "kind": "sale",
                    "amount": amount,
                    "status": "success",
                    "source_name": "web",
                }
            },
            timeout=60,
        )
        r.raise_for_status()
        return self.get_order(woo_order_id)

    # --------------------------------------------------------------- products

    def batch_products(
        self,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[int] | None = None,
    ) -> dict:
        """Emulate Woo's POST /products/batch with per-product Sapo requests.

        Returns ``{"create": [...], "update": [...], "delete": [...]}`` in
        request order, each item either ``{"id", "sku"}`` (success) or a
        Woo-shaped ``{"error": {"code", "message"}}`` reject (updates echo the
        requested ``id``), so ``_save_mappings`` / ``_collect_batch_failures``
        / the stale-id recovery in the catalog service all work unchanged.
        """
        return {
            "create": [self._create_product(item) for item in create or []],
            "update": [self._update_product(item) for item in update or []],
            "delete": [self._delete_product(pid) for pid in delete or []],
        }

    def _create_product(self, item: dict) -> dict:
        guard = _guard_item(item)
        if guard:
            return {"error": guard}
        product = _woo_product_to_sapo(item)
        if item.get("type") == "variable":
            options, placeholder = _variable_options(item)
            product["options"] = options
            product["variants"] = [placeholder]
        else:
            product["variants"] = [_default_variant(item)]
        r = self._request("POST", "/products.json", json={"product": product}, timeout=60)
        if r.status_code >= 400:
            return {"error": self._http_error(r)}
        created = r.json().get("product") or {}
        self._sync_collects(created.get("id"), item.get("categories"), diff=False)
        return {"id": created.get("id"), "sku": item.get("sku", "")}

    def _update_product(self, item: dict) -> dict:
        product_id = item.get("id")
        guard = _guard_item(item)
        if guard:
            return {"id": product_id, "error": guard}
        # Read first: confirms the product still exists (404 → stale-id code so
        # the service re-creates it) and yields the default variant's id so the
        # PUT updates that variant IN PLACE — never ship a variants array
        # without ids (a Shopify-style replace would churn variant ids).
        r = self._request("GET", f"/products/{product_id}.json")
        if r.status_code == 404:
            return {"id": product_id, "error": dict(_INVALID_ID_ERROR)}
        if r.status_code >= 400:
            return {"id": product_id, "error": self._http_error(r)}
        remote = r.json().get("product") or {}

        product = _woo_product_to_sapo(item)
        if item.get("type") != "variable":
            variant = _default_variant(item)
            existing = (remote.get("variants") or [{}])[0]
            if existing.get("id"):
                variant["id"] = existing["id"]
            product["variants"] = [variant]
        # variable: options/variants flow through batch_variations; only
        # product-level fields are updated here (option renames don't
        # propagate — documented v1 limitation).

        r = self._request(
            "PUT", f"/products/{product_id}.json", json={"product": product}, timeout=60
        )
        if r.status_code == 404:
            return {"id": product_id, "error": dict(_INVALID_ID_ERROR)}
        if r.status_code >= 400:
            return {"id": product_id, "error": self._http_error(r)}
        self._sync_collects(product_id, item.get("categories"), diff=True)
        return {"id": product_id, "sku": item.get("sku", "")}

    def _delete_product(self, product_id) -> dict:
        r = self._request("DELETE", f"/products/{product_id}.json")
        if r.status_code == 404 or r.status_code < 400:  # idempotent delete
            return {"id": product_id}
        # error → the service keeps the mapping and retries next run
        return {"id": product_id, "error": self._http_error(r)}

    def _sync_collects(self, product_id, category_refs, *, diff: bool) -> None:
        """Align the product's collections with the payload's ``{"id"}`` refs.

        Sapo links products to collections via separate Collect objects, not a
        field on the product. Best-effort by design: the product write already
        succeeded, so a collect failure must not turn the item into a reject —
        it is logged and self-heals on the next push (diff re-runs every
        update). ``{"name"}`` refs are ignored, mirroring Woo's behavior.
        """
        if not product_id:
            return
        wanted = {ref["id"] for ref in category_refs or [] if ref.get("id")}
        try:
            existing: dict = {}
            if diff:
                r = self._request(
                    "GET",
                    "/collects.json",
                    params={"product_id": product_id, "limit": _PAGE_LIMIT},
                )
                if r.status_code < 400:
                    for c in r.json().get("collects") or []:
                        existing[c.get("collection_id")] = c.get("id")
            for collection_id in wanted - set(existing):
                self._request(
                    "POST",
                    "/collects.json",
                    json={"collect": {"product_id": product_id, "collection_id": collection_id}},
                )  # a 422 (e.g. smart collection) is returned, not raised → skipped
            for collection_id, collect_id in existing.items():
                if collection_id not in wanted:
                    self._request("DELETE", f"/collects/{collect_id}.json")
        except httpx.HTTPError:
            logger.warning(
                "sapo collects sync failed for product_id=%s (will self-heal next push)",
                product_id,
            )

    # ------------------------------------------------------------- variations

    def batch_variations(
        self,
        parent_id: int,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[int] | None = None,
    ) -> dict:
        """Emulate Woo's variations batch with per-variant Sapo requests.

        Success items are ``{"id": <variant_id>, "sku"}`` (what
        ``_save_variation_mappings`` matches); rejects omit the id/sku pair so
        they are skipped there and retried next run. The first create consumes
        the placeholder variant (sku-less, shipped with the parent create) by
        overwriting it in place — see ``_variable_options``.
        """
        result: dict = {"create": [], "update": [], "delete": []}

        r = self._request("GET", f"/products/{parent_id}.json")
        if r.status_code >= 400:
            err = dict(_INVALID_ID_ERROR) if r.status_code == 404 else self._http_error(r)
            result["create"] = [{"error": dict(err)} for _ in create or []]
            result["update"] = [{"id": it.get("id"), "error": dict(err)} for it in update or []]
            result["delete"] = [{"id": vid, "error": dict(err)} for vid in delete or []]
            return result
        remote = r.json().get("product") or {}
        option_names = [o.get("name", "") for o in remote.get("options") or []]
        placeholder_id = next(
            (v.get("id") for v in remote.get("variants") or [] if not (v.get("sku") or "").strip()),
            None,
        )

        for item in create or []:
            variant, unknown = _woo_variation_to_sapo(item, option_names)
            if unknown:
                result["create"].append(self._option_mismatch(unknown))
                continue
            if placeholder_id:
                r = self._request(
                    "PUT",
                    f"/products/{parent_id}/variants/{placeholder_id}.json",
                    json={"variant": {"id": placeholder_id, **variant}},
                    timeout=60,
                )
                placeholder_id = None  # consumed either way — keeps combos deterministic
            else:
                r = self._request(
                    "POST",
                    f"/products/{parent_id}/variants.json",
                    json={"variant": variant},
                    timeout=60,
                )
            if r.status_code >= 400:
                result["create"].append({"error": self._http_error(r)})
            else:
                got = r.json().get("variant") or {}
                result["create"].append({"id": got.get("id"), "sku": item.get("sku", "")})

        for item in update or []:
            variant_id = item.get("id")
            variant, unknown = _woo_variation_to_sapo(item, option_names)
            if unknown:
                result["update"].append({"id": variant_id, **self._option_mismatch(unknown)})
                continue
            r = self._request(
                "PUT",
                f"/products/{parent_id}/variants/{variant_id}.json",
                json={"variant": {"id": variant_id, **variant}},
                timeout=60,
            )
            if r.status_code >= 400:
                # no "sku" on the reject → _save_variation_mappings skips it
                result["update"].append({"id": variant_id, "error": self._http_error(r)})
            else:
                result["update"].append({"id": variant_id, "sku": item.get("sku", "")})

        for variant_id in delete or []:
            r = self._request("DELETE", f"/products/{parent_id}/variants/{variant_id}.json")
            if r.status_code == 404 or r.status_code < 400:
                result["delete"].append({"id": variant_id})
            else:
                result["delete"].append({"id": variant_id, "error": self._http_error(r)})

        return result

    @staticmethod
    def _option_mismatch(unknown: list[str]) -> dict:
        return {
            "error": {
                "code": "sapo_option_mismatch",
                "message": (
                    "Thuộc tính biến thể không khớp options của sản phẩm trên Sapo: "
                    + ", ".join(unknown)
                ),
            }
        }

    # ------------------------------------------------------------- categories

    def _list_collections(self) -> list[dict]:
        """Every custom collection of the store (paginated, raw Sapo dicts)."""
        collections: list[dict] = []
        page = 1
        while True:
            r = self._request(
                "GET",
                "/custom_collections.json",
                params={"limit": _PAGE_LIMIT, "page": page},
            )
            r.raise_for_status()
            batch = r.json().get("custom_collections") or []
            collections.extend(batch)
            if len(batch) < _PAGE_LIMIT:
                break
            page += 1
        return collections

    def list_categories(self, per_page: int = 100) -> list[dict]:
        """Custom collections as Woo-category-shaped dicts for the Hub pull.

        Sapo collections are FLAT, so every one maps to a root category
        (``parent: 0``) — ``pull_categories_for_site`` consumes this unchanged.
        The collection name lives in ``name`` and the slug in ``alias`` (Sapo's
        custom_collection has no ``title`` field, unlike Shopify); a category
        with an empty name is skipped by the pull, so this must read the right
        field or every Sapo category silently disappears.
        """
        return [
            {
                "id": c.get("id"),
                "name": c.get("name") or "",
                "slug": c.get("alias") or "",
                "parent": 0,
            }
            for c in self._list_collections()
        ]

    def batch_categories(self, create: list[dict] | None = None) -> dict:
        """Create custom collections, emulating Woo's term_exists semantics.

        Sapo happily creates duplicate collection titles, so existing titles
        are detected up front (one paginated listing per call) and answered
        with a Woo-shaped ``term_exists`` reject carrying the existing id in
        ``error.data.resource_id`` — ``_ensure_site_categories`` then links the
        mapping instead of duplicating the collection. ``parent`` refs are
        ignored: Sapo collections have no hierarchy.
        """
        items = create or []
        if not items:
            return {"create": []}
        existing: dict = {}
        for c in self._list_collections():
            existing.setdefault(_normalize_title(c.get("name") or ""), c.get("id"))

        out = []
        for item in items:
            name = item.get("name", "")
            key = _normalize_title(name)
            if key in existing and existing[key]:
                out.append(
                    {
                        "id": 0,
                        "error": {
                            "code": "term_exists",
                            "message": "Collection đã tồn tại trên Sapo.",
                            "data": {"resource_id": existing[key]},
                        },
                    }
                )
                continue
            r = self._request(
                "POST",
                "/custom_collections.json",
                json={"custom_collection": {"name": name}},
                timeout=60,
            )
            if r.status_code >= 400:
                out.append({"error": self._http_error(r)})
                continue
            created = r.json().get("custom_collection") or {}
            existing[key] = created.get("id")
            out.append({"id": created.get("id"), "name": created.get("name") or name})
        return {"create": out}

    # ------------------------------------------------------------ healthcheck

    def system_status(self) -> dict:
        """GET /admin/custom_collections.json — verifies the private app's key works.

        Mirrors WooClient.system_status: callers only need success/raise, and
        the timeout is tunable via SITE_HEALTHCHECK_TIMEOUT_SECONDS. Uses the
        collections list (already exercised by the pull flow, so the private app
        provably has scope for it) with ``limit=1`` to keep the payload tiny — a
        live store returns 200 even when empty, while a bad key still raises.
        """
        r = self._request(
            "GET", "/custom_collections.json", params={"limit": 1}, timeout=self._status_timeout
        )
        r.raise_for_status()
        return r.json()
