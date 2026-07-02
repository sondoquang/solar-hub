"""Unit tests for SapoClient — the Woo-shaped adapter over the Sapo admin API.

No network: the pooled client's ``request`` is monkeypatched with a recording fake, so the
tests assert both the Sapo-bound requests (URLs, wrapped bodies) and the
Woo-shaped responses the catalog service consumes.
"""

import httpx
import pytest

from apps.integrations import sapo
from apps.integrations.sapo import (
    SapoClient,
    _inventory_fields,
    _price_fields,
    _woo_variation_to_sapo,
)


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://store.mysapo.net"),
                response=self,  # type: ignore[arg-type]
            )


class _FakeHttp:
    """Routes (method, path-suffix) to canned responses, recording every call."""

    def __init__(self, routes=None, default=None):
        self.routes = routes or []  # list of (method, path_contains, response_or_fn)
        self.default = default or _FakeResponse(200, {})
        self.calls = []  # dicts: method, url, json, params

    def __call__(self, method, url, *, json=None, params=None, auth=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params})
        for m, fragment, resp in self.routes:
            if m == method and fragment in url:
                return resp(self.calls[-1]) if callable(resp) else resp
        return self.default

    def sent(self, method, fragment):
        return [c for c in self.calls if c["method"] == method and fragment in c["url"]]


def _client():
    return SapoClient(
        "https://store.mysapo.net",
        "key",
        "secret",
        throttle_seconds=0,  # no pacing in tests
    )


def _patch(monkeypatch, fake):
    # All Sapo traffic goes through the module-level pooled client's ``request``.
    monkeypatch.setattr(sapo._POOL, "request", fake)


# ----------------------------------------------------------- pure translators


def test_price_fields_sale_maps_to_price_and_compare():
    assert _price_fields("100000.00", "80000.00") == {
        "price": 80000.0,
        "compare_at_price": 100000.0,
    }


def test_price_fields_without_sale_clears_compare():
    assert _price_fields("100000.00", "") == {"price": 100000.0, "compare_at_price": None}


def test_price_fields_empty_defaults_to_zero():
    assert _price_fields("", "")["price"] == 0


@pytest.mark.parametrize(
    "stock_status,expected_management,expected_policy",
    [
        ("instock", None, None),
        ("outofstock", "sapo", "deny"),
        ("onbackorder", "sapo", "continue"),
    ],
)
def test_inventory_fields(stock_status, expected_management, expected_policy):
    fields = _inventory_fields(stock_status)
    assert fields["inventory_management"] == expected_management
    if expected_policy:
        assert fields["inventory_policy"] == expected_policy
        assert fields["inventory_quantity"] == 0


def test_variation_maps_options_by_parent_order():
    variant, unknown = _woo_variation_to_sapo(
        {
            "sku": "SP-1-RED-L",
            "regular_price": "10",
            "attributes": [{"name": "Size", "option": "L"}, {"name": "Màu", "option": "Đỏ"}],
        },
        ["Màu", "Size"],
    )
    assert unknown == []
    assert variant["option1"] == "Đỏ"
    assert variant["option2"] == "L"


def test_variation_reports_unknown_attribute():
    _, unknown = _woo_variation_to_sapo(
        {"sku": "X", "attributes": [{"name": "Chất liệu", "option": "Nhôm"}]},
        ["Màu"],
    )
    assert unknown == ["Chất liệu"]


# ------------------------------------------------------------------- products


def test_create_simple_product_posts_wrapped_payload_and_collects(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "POST",
                "/admin/products.json",
                _FakeResponse(201, {"product": {"id": 9001}}),
            ),
            ("POST", "/admin/collects.json", _FakeResponse(201, {"collect": {"id": 1}})),
        ]
    )
    _patch(monkeypatch, fake)
    resp = _client().batch_products(
        create=[
            {
                "name": "Pin 100W",
                "sku": "SP-1",
                "type": "simple",
                "description": "<p>desc</p>",
                "short_description": "short",
                "regular_price": "100000.00",
                "sale_price": "80000.00",
                "status": "publish",
                "stock_status": "instock",
                "weight": "1.500",
                "categories": [{"id": 5}, {"name": "Chưa map"}],
                "images": [{"src": "https://hub/img.png"}],
            }
        ]
    )
    assert resp["create"] == [{"id": 9001, "sku": "SP-1"}]

    body = fake.sent("POST", "/admin/products.json")[0]["json"]["product"]
    assert body["name"] == "Pin 100W"
    assert body["content"] == "<p>desc</p>"
    assert body["summary"] == "short"
    assert body["published_on"]  # publish → timestamped
    assert body["images"] == [{"src": "https://hub/img.png", "position": 1}]
    variant = body["variants"][0]
    assert variant["sku"] == "SP-1"
    assert variant["price"] == 80000.0
    assert variant["compare_at_price"] == 100000.0
    assert variant["weight"] == 1.5

    # only the {"id"} category ref becomes a Collect; {"name"} refs are ignored
    collects = fake.sent("POST", "/admin/collects.json")
    assert len(collects) == 1
    assert collects[0]["json"]["collect"] == {"product_id": 9001, "collection_id": 5}


@pytest.mark.parametrize("ptype", ["grouped", "external"])
def test_unsupported_types_rejected_without_http(monkeypatch, ptype):
    fake = _FakeHttp()
    _patch(monkeypatch, fake)
    resp = _client().batch_products(create=[{"sku": "SP-G", "type": ptype}])
    assert resp["create"][0]["error"]["code"] == "sapo_unsupported_type"
    assert "id" not in resp["create"][0]
    assert fake.calls == []


def test_variable_with_too_many_attributes_rejected(monkeypatch):
    fake = _FakeHttp()
    _patch(monkeypatch, fake)
    attrs = [{"name": f"A{i}", "options": ["x"], "variation": True} for i in range(4)]
    resp = _client().batch_products(
        create=[{"sku": "SP-V", "type": "variable", "attributes": attrs}]
    )
    assert resp["create"][0]["error"]["code"] == "sapo_max_options_exceeded"
    assert fake.calls == []


def test_create_variable_ships_options_and_placeholder_variant(monkeypatch):
    fake = _FakeHttp(
        routes=[("POST", "/admin/products.json", _FakeResponse(201, {"product": {"id": 9100}}))]
    )
    _patch(monkeypatch, fake)
    resp = _client().batch_products(
        create=[
            {
                "name": "Áo",
                "sku": "SP-V",
                "type": "variable",
                "attributes": [
                    {"name": "Màu", "options": ["Đỏ", "Xanh"], "variation": True},
                    {"name": "Size", "options": ["M", "L"], "variation": True},
                    {"name": "Hãng", "options": ["X"], "variation": False},  # not an option
                ],
            }
        ]
    )
    assert resp["create"] == [{"id": 9100, "sku": "SP-V"}]
    body = fake.sent("POST", "/admin/products.json")[0]["json"]["product"]
    assert body["options"] == [{"name": "Màu"}, {"name": "Size"}]
    placeholder = body["variants"][0]
    assert placeholder["sku"] == ""
    assert placeholder["option1"] == "Đỏ"
    assert placeholder["option2"] == "M"


def test_update_of_deleted_product_maps_to_stale_id_code(monkeypatch):
    fake = _FakeHttp(routes=[("GET", "/admin/products/123.json", _FakeResponse(404))])
    _patch(monkeypatch, fake)
    resp = _client().batch_products(update=[{"id": 123, "sku": "SP-1", "type": "simple"}])
    item = resp["update"][0]
    assert item["id"] == 123
    assert item["error"]["code"] == "woocommerce_rest_product_invalid_id"


def test_update_simple_reuses_variant_id_and_diffs_collects(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/products/123.json",
                _FakeResponse(
                    200, {"product": {"id": 123, "variants": [{"id": 77, "sku": "SP-1"}]}}
                ),
            ),
            ("PUT", "/admin/products/123.json", _FakeResponse(200, {"product": {"id": 123}})),
            (
                "GET",
                "/admin/collects.json",
                _FakeResponse(
                    200,
                    {
                        "collects": [
                            {"id": 100, "collection_id": 5},  # wanted → kept
                            {"id": 101, "collection_id": 9},  # stale → deleted
                        ]
                    },
                ),
            ),
            ("POST", "/admin/collects.json", _FakeResponse(201, {"collect": {"id": 102}})),
            ("DELETE", "/admin/collects/101.json", _FakeResponse(200, {})),
        ]
    )
    _patch(monkeypatch, fake)
    resp = _client().batch_products(
        update=[
            {
                "id": 123,
                "sku": "SP-1",
                "type": "simple",
                "regular_price": "50",
                "categories": [{"id": 5}, {"id": 6}],
            }
        ]
    )
    assert resp["update"] == [{"id": 123, "sku": "SP-1"}]
    put_body = fake.sent("PUT", "/admin/products/123.json")[0]["json"]["product"]
    assert put_body["variants"][0]["id"] == 77  # updated in place, never replaced
    created = fake.sent("POST", "/admin/collects.json")
    assert [c["json"]["collect"]["collection_id"] for c in created] == [6]
    assert len(fake.sent("DELETE", "/admin/collects/101.json")) == 1


def test_delete_404_is_idempotent_success(monkeypatch):
    fake = _FakeHttp(routes=[("DELETE", "/admin/products/55.json", _FakeResponse(404))])
    _patch(monkeypatch, fake)
    resp = _client().batch_products(delete=[55])
    assert resp["delete"] == [{"id": 55}]


def test_429_retries_then_succeeds(monkeypatch):
    attempts = []

    def handler(call):
        attempts.append(1)
        if len(attempts) < 3:
            return _FakeResponse(429, headers={"Retry-After": "0.01"})
        return _FakeResponse(200, {"product": {"id": 1}})

    fake = _FakeHttp(routes=[("POST", "/admin/products.json", handler)])
    _patch(monkeypatch, fake)
    sleeps = []
    monkeypatch.setattr(sapo.time, "sleep", sleeps.append)
    resp = _client().batch_products(create=[{"sku": "S", "type": "simple"}])
    assert resp["create"][0]["id"] == 1
    assert len(attempts) == 3
    assert sleeps.count(0.01) == 2  # slept Retry-After before each retry


def test_429_exhausted_raises(monkeypatch):
    fake = _FakeHttp(default=_FakeResponse(429, headers={"Retry-After": "0"}))
    _patch(monkeypatch, fake)
    monkeypatch.setattr(sapo.time, "sleep", lambda s: None)
    client = SapoClient(
        "https://store.mysapo.net", "k", "s", throttle_seconds=0, max_429_retries=1
    )
    with pytest.raises(httpx.HTTPError):
        client.batch_products(create=[{"sku": "S", "type": "simple"}])


# ----------------------------------------------------------------- variations


def _parent_routes(extra=None):
    parent = _FakeResponse(
        200,
        {
            "product": {
                "id": 9100,
                "options": [{"name": "Màu"}, {"name": "Size"}],
                "variants": [{"id": 50, "sku": ""}],  # placeholder from the create
            }
        },
    )
    return [("GET", "/admin/products/9100.json", parent)] + (extra or [])


def test_first_variation_overwrites_placeholder_then_posts(monkeypatch):
    fake = _FakeHttp(
        routes=_parent_routes(
            [
                (
                    "PUT",
                    "/admin/products/9100/variants/50.json",
                    _FakeResponse(200, {"variant": {"id": 50}}),
                ),
                (
                    "POST",
                    "/admin/products/9100/variants.json",
                    _FakeResponse(201, {"variant": {"id": 51}}),
                ),
            ]
        )
    )
    _patch(monkeypatch, fake)
    resp = _client().batch_variations(
        9100,
        create=[
            {
                "sku": "V-1",
                "regular_price": "10",
                "attributes": [{"name": "Màu", "option": "Đỏ"}],
            },
            {
                "sku": "V-2",
                "regular_price": "12",
                "attributes": [{"name": "Màu", "option": "Xanh"}],
            },
        ],
    )
    assert resp["create"] == [{"id": 50, "sku": "V-1"}, {"id": 51, "sku": "V-2"}]
    put_body = fake.sent("PUT", "/variants/50.json")[0]["json"]["variant"]
    assert put_body["option1"] == "Đỏ"
    post_body = fake.sent("POST", "/variants.json")[0]["json"]["variant"]
    assert post_body["option1"] == "Xanh"


def test_variation_with_unknown_attribute_rejected(monkeypatch):
    fake = _FakeHttp(routes=_parent_routes())
    _patch(monkeypatch, fake)
    resp = _client().batch_variations(
        9100,
        create=[{"sku": "V-X", "attributes": [{"name": "Chất liệu", "option": "Nhôm"}]}],
    )
    item = resp["create"][0]
    assert item["error"]["code"] == "sapo_option_mismatch"
    assert "id" not in item  # skipped by _save_variation_mappings


def test_variations_of_deleted_parent_all_fail_with_stale_code(monkeypatch):
    fake = _FakeHttp(routes=[("GET", "/admin/products/9100.json", _FakeResponse(404))])
    _patch(monkeypatch, fake)
    resp = _client().batch_variations(9100, create=[{"sku": "V-1"}], delete=[7])
    assert resp["create"][0]["error"]["code"] == "woocommerce_rest_product_invalid_id"
    assert resp["delete"][0]["error"]["code"] == "woocommerce_rest_product_invalid_id"


def test_update_variation_error_omits_sku(monkeypatch):
    fake = _FakeHttp(
        routes=_parent_routes(
            [
                (
                    "PUT",
                    "/admin/products/9100/variants/60.json",
                    _FakeResponse(422, {"errors": "bad"}),
                )
            ]
        )
    )
    _patch(monkeypatch, fake)
    resp = _client().batch_variations(
        9100, update=[{"id": 60, "sku": "V-1", "attributes": [{"name": "Màu", "option": "Đỏ"}]}]
    )
    item = resp["update"][0]
    assert item["error"]["code"] == "sapo_http_422"
    assert "sku" not in item  # error rows must not become mappings


# ----------------------------------------------------------------- categories


def test_list_categories_maps_collections_to_root_categories(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/custom_collections.json",
                _FakeResponse(
                    200,
                    {
                        "custom_collections": [
                            {"id": 4, "name": "Pin Mặt Trời", "alias": "pin-mat-troi"}
                        ]
                    },
                ),
            )
        ]
    )
    _patch(monkeypatch, fake)
    assert _client().list_categories() == [
        {"id": 4, "name": "Pin Mặt Trời", "slug": "pin-mat-troi", "parent": 0}
    ]


def test_batch_categories_emulates_term_exists_and_creates_missing(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/custom_collections.json",
                _FakeResponse(200, {"custom_collections": [{"id": 4, "name": "Pin Mặt Trời"}]}),
            ),
            (
                "POST",
                "/admin/custom_collections.json",
                _FakeResponse(201, {"custom_collection": {"id": 8, "name": "Inverter"}}),
            ),
        ]
    )
    _patch(monkeypatch, fake)
    resp = _client().batch_categories(
        create=[{"name": "pin  mặt trời", "parent": 3}, {"name": "Inverter"}]
    )
    dup, created = resp["create"]
    assert dup["error"]["code"] == "term_exists"
    assert dup["error"]["data"]["resource_id"] == 4
    assert created == {"id": 8, "name": "Inverter"}
    # parent refs are ignored — collections are flat
    assert fake.sent("POST", "/admin/custom_collections.json")[0]["json"] == {
        "custom_collection": {"name": "Inverter"}
    }


def test_system_status_hits_custom_collections(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/custom_collections.json",
                _FakeResponse(200, {"custom_collections": []}),
            )
        ]
    )
    _patch(monkeypatch, fake)
    assert _client().system_status() == {"custom_collections": []}
    assert fake.sent("GET", "/admin/custom_collections.json")[0]["params"] == {"limit": 1}


def test_system_status_raises_on_bad_key(monkeypatch):
    fake = _FakeHttp(routes=[("GET", "/admin/custom_collections.json", _FakeResponse(401))])
    _patch(monkeypatch, fake)
    with pytest.raises(httpx.HTTPError):
        _client().system_status()


def test_request_follows_redirect_to_sapo_host(monkeypatch):
    # A custom storefront domain 302-redirects /admin/*.json to *.mysapo.net;
    # the request must be re-issued there (httpx would drop auth cross-host).
    def handler(call):
        if "mysapo.net" in call["url"]:
            return _FakeResponse(200, {"custom_collections": []})
        return _FakeResponse(
            302,
            headers={"Location": "https://shop.mysapo.net/admin/custom_collections.json?limit=1"},
        )

    fake = _FakeHttp(routes=[("GET", "/admin/custom_collections.json", handler)])
    _patch(monkeypatch, fake)
    client = SapoClient("https://shop.example.com", "key", "secret", throttle_seconds=0)
    assert client.system_status() == {"custom_collections": []}
    urls = [c["url"] for c in fake.calls]
    assert urls[0].startswith("https://shop.example.com/admin/")
    assert urls[1].startswith("https://shop.mysapo.net/admin/")
    # the canonical store host (post-redirect) is recorded for store dedup
    assert client.resolved_host == "shop.mysapo.net"


def test_request_does_not_follow_redirect_to_foreign_host(monkeypatch):
    # A redirect away from a Sapo host must not replay the API credentials.
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/custom_collections.json",
                _FakeResponse(302, headers={"Location": "https://evil.example.org/steal"}),
            )
        ]
    )
    _patch(monkeypatch, fake)
    client = SapoClient("https://shop.example.com", "key", "secret", throttle_seconds=0)
    r = client._request("GET", "/custom_collections.json")
    assert r.status_code == 302  # returned unfollowed → system_status raises on it
    assert all("evil.example.org" not in c["url"] for c in fake.calls)
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------- orders


def _sapo_order(**overrides):
    order = {
        "id": 450789469,
        "name": "#1001",
        "order_number": 1001,
        "status": "open",
        "financial_status": "paid",
        "created_on": "2024-01-15T10:30:00Z",
        "modified_on": "2024-01-16T14:22:15Z",
        "total_price": "409.94",
        "currency": "VND",
        "email": "bob@example.com",
        "note": "giao giờ hành chính",
        "customer": {"first_name": "Bob", "last_name": "Norman", "phone": "0901234567"},
        "billing_address": {
            "first_name": "Bob",
            "last_name": "Norman",
            "phone": "0901234567",
            "address1": "123 Lê Lợi",
            "city": "Hà Nội",
            "province": "Hà Nội",
            "zip": "100000",
            "country": "Vietnam",
        },
        "shipping_address": {"address1": "456 Trần Hưng Đạo", "city": "Hà Nội"},
        "line_items": [
            {"sku": "SP-1", "title": "Pin 100W", "quantity": 2, "price": "150.00"}
        ],
    }
    order.update(overrides)
    return order


def test_sapo_order_to_woo_maps_hub_fields():
    woo = sapo._sapo_order_to_woo(_sapo_order())
    assert woo["id"] == 450789469
    assert woo["number"] == "1001"  # "#1001" → bare number; FE prepends the "#"
    assert woo["status"] == "processing"  # open → processing
    assert woo["currency"] == "VND"
    assert woo["total"] == "409.94"
    assert woo["customer_note"] == "giao giờ hành chính"
    assert woo["date_created_gmt"] == "2024-01-15T10:30:00Z"
    assert woo["date_modified_gmt"] == "2024-01-16T14:22:15Z"
    # billing address remapped to Woo keys
    assert woo["billing"]["address_1"] == "123 Lê Lợi"
    assert woo["billing"]["state"] == "Hà Nội"
    assert woo["billing"]["postcode"] == "100000"
    assert woo["billing"]["email"] == "bob@example.com"
    # line item: name from title, total = price * quantity
    assert woo["line_items"] == [
        {"sku": "SP-1", "name": "Pin 100W", "quantity": 2, "total": "300.0"}
    ]


@pytest.mark.parametrize(
    "sapo_status,woo_status",
    [("open", "processing"), ("closed", "completed"), ("cancelled", "cancelled")],
)
def test_sapo_order_status_maps_to_woo(sapo_status, woo_status):
    woo = sapo._sapo_order_to_woo(_sapo_order(status=sapo_status))
    assert woo["status"] == woo_status


def test_sapo_order_backfills_name_phone_from_customer():
    # An order whose billing address omits name/phone still classifies, because
    # the customer object backfills them.
    order = _sapo_order(billing_address={"address1": "1 Đường A", "city": "HCM"})
    woo = sapo._sapo_order_to_woo(order)
    assert woo["billing"]["first_name"] == "Bob"
    assert woo["billing"]["phone"] == "0901234567"
    assert woo["billing"]["email"] == "bob@example.com"


def test_list_orders_maps_params_and_returns_woo_shape(monkeypatch):
    fake = _FakeHttp(
        routes=[("GET", "/admin/orders.json", _FakeResponse(200, {"orders": [_sapo_order()]}))]
    )
    _patch(monkeypatch, fake)
    orders = _client().list_orders(
        status="processing",
        per_page=100,
        modified_after="2024-01-01T00:00:00",
    )
    assert orders[0]["status"] == "processing"
    params = fake.sent("GET", "/admin/orders.json")[0]["params"]
    assert params["status"] == "open"  # processing → open
    assert params["limit"] == 100
    assert params["modified_on_min"] == "2024-01-01T00:00:00Z"  # naive → UTC-stamped
    assert "created_on_min" not in params


def test_list_orders_date_range_maps_to_created_on_bounds(monkeypatch):
    fake = _FakeHttp(
        routes=[("GET", "/admin/orders.json", _FakeResponse(200, {"orders": []}))]
    )
    _patch(monkeypatch, fake)
    _client().list_orders(
        status="completed", after="2024-01-01T00:00:00", before="2024-01-31T23:59:59"
    )
    params = fake.sent("GET", "/admin/orders.json")[0]["params"]
    assert params["status"] == "closed"  # completed → closed
    assert params["created_on_min"] == "2024-01-01T00:00:00Z"  # naive → UTC-stamped
    assert params["created_on_max"] == "2024-01-31T23:59:59Z"


def test_list_orders_unsupported_woo_status_skips_http(monkeypatch):
    # Sapo has no pending/on-hold/refunded/failed — the poll must not query.
    fake = _FakeHttp()
    _patch(monkeypatch, fake)
    assert _client().list_orders(status="on-hold") == []
    assert fake.calls == []


def test_list_orders_paginates_by_page_until_short_page(monkeypatch):
    # Sapo honors `page`: page 1 full (250) → fetch page 2; page 2 short → stop.
    full = {"orders": [_sapo_order(id=i) for i in range(1, 251)]}

    def handler(call):
        if call["params"]["page"] == 1:
            return _FakeResponse(200, full)
        return _FakeResponse(200, {"orders": [_sapo_order(id=999)]})

    fake = _FakeHttp(routes=[("GET", "/admin/orders.json", handler)])
    _patch(monkeypatch, fake)
    orders = _client().list_orders(status="processing", per_page=250)
    assert len(orders) == 251
    pages = [c["params"]["page"] for c in fake.sent("GET", "/admin/orders.json")]
    assert pages == [1, 2]


def test_list_orders_stops_at_page_cap(monkeypatch):
    # A misbehaving endpoint that never returns a short page must not loop
    # forever — the _MAX_ORDER_PAGES backstop bounds it.
    monkeypatch.setattr(sapo, "_MAX_ORDER_PAGES", 3)
    always_full = {"orders": [_sapo_order(id=i) for i in range(1, 251)]}
    fake = _FakeHttp(routes=[("GET", "/admin/orders.json", _FakeResponse(200, always_full))])
    _patch(monkeypatch, fake)
    orders = _client().list_orders(status="processing", per_page=250)
    assert len(fake.sent("GET", "/admin/orders.json")) == 3  # capped, no infinite loop
    assert len(orders) == 750


def test_update_order_completed_closes_and_returns_woo(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "POST",
                "/admin/orders/77/close.json",
                _FakeResponse(200, {"order": _sapo_order(id=77, status="closed")}),
            )
        ]
    )
    _patch(monkeypatch, fake)
    woo = _client().update_order(77, status="completed")
    assert woo["id"] == 77
    assert woo["status"] == "completed"
    assert fake.sent("POST", "/admin/orders/77/close.json")[0]["json"] == {}


def test_update_order_cancelled_hits_cancel_endpoint(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "POST",
                "/admin/orders/88/cancel.json",
                _FakeResponse(200, {"order": _sapo_order(id=88, status="cancelled")}),
            )
        ]
    )
    _patch(monkeypatch, fake)
    woo = _client().update_order(88, status="cancelled")
    assert woo["status"] == "cancelled"
    assert len(fake.sent("POST", "/admin/orders/88/cancel.json")) == 1


def test_update_order_unsupported_status_raises():
    with pytest.raises(NotImplementedError):
        _client().update_order(1, status="processing")


def test_sapo_order_to_woo_carries_financial_status():
    woo = sapo._sapo_order_to_woo(_sapo_order(financial_status="pending"))
    assert woo["financial_status"] == "pending"


def test_sapo_order_to_woo_financial_status_defaults_blank():
    order = _sapo_order()
    del order["financial_status"]
    assert sapo._sapo_order_to_woo(order)["financial_status"] == ""


def test_list_orders_unpaid_group_expands_to_one_query_per_literal_status(monkeypatch):
    # Sapo has no "unpaid" group alias, so the poll's "unpaid" must fan out to
    # one query per literal unpaid status — never sending the literal "unpaid".
    def handler(call):
        fs = call["params"]["financial_status"]
        if fs == "pending":
            return _FakeResponse(200, {"orders": [_sapo_order(id=1, financial_status="pending")]})
        return _FakeResponse(200, {"orders": []})

    fake = _FakeHttp(routes=[("GET", "/admin/orders.json", handler)])
    _patch(monkeypatch, fake)
    orders = _client().list_orders(status="processing", financial_status="unpaid")
    sent = [c["params"]["financial_status"] for c in fake.sent("GET", "/admin/orders.json")]
    assert sent == ["pending", "authorized", "partially_paid"]
    assert "unpaid" not in sent
    # the one matched (pending) order is returned, Woo-shaped
    assert [o["id"] for o in orders] == [1]


def test_list_orders_passes_single_literal_financial_status(monkeypatch):
    # A concrete status (not the group) is sent through verbatim, one query.
    fake = _FakeHttp(
        routes=[("GET", "/admin/orders.json", _FakeResponse(200, {"orders": []}))]
    )
    _patch(monkeypatch, fake)
    _client().list_orders(status="processing", financial_status="paid")
    sent = fake.sent("GET", "/admin/orders.json")
    assert len(sent) == 1
    assert sent[0]["params"]["financial_status"] == "paid"


def test_list_orders_stamps_utc_on_naive_date_filters(monkeypatch):
    # Sapo silently ignores a timezone-naive date filter, so the naive bounds /
    # watermark the orders service builds must go out carrying a 'Z'.
    fake = _FakeHttp(
        routes=[("GET", "/admin/orders.json", _FakeResponse(200, {"orders": []}))]
    )
    _patch(monkeypatch, fake)
    _client().list_orders(
        status="completed",
        after="2024-01-01T00:00:00",
        before="2024-01-31T23:59:59.999999",
        modified_after="2024-02-01T10:00:00",
    )
    params = fake.sent("GET", "/admin/orders.json")[0]["params"]
    assert params["created_on_min"] == "2024-01-01T00:00:00Z"
    assert params["created_on_max"] == "2024-01-31T23:59:59.999999Z"
    assert params["modified_on_min"] == "2024-02-01T10:00:00Z"


def test_list_orders_keeps_existing_timezone_on_date_filters(monkeypatch):
    # An aware watermark ('+00:00' from datetime.isoformat) must pass unchanged.
    fake = _FakeHttp(
        routes=[("GET", "/admin/orders.json", _FakeResponse(200, {"orders": []}))]
    )
    _patch(monkeypatch, fake)
    _client().list_orders(status="processing", modified_after="2024-02-01T10:00:00+00:00")
    params = fake.sent("GET", "/admin/orders.json")[0]["params"]
    assert params["modified_on_min"] == "2024-02-01T10:00:00+00:00"


def test_list_orders_omits_financial_status_when_absent(monkeypatch):
    fake = _FakeHttp(
        routes=[("GET", "/admin/orders.json", _FakeResponse(200, {"orders": []}))]
    )
    _patch(monkeypatch, fake)
    _client().list_orders(status="processing")
    params = fake.sent("GET", "/admin/orders.json")[0]["params"]
    assert "financial_status" not in params


def test_get_order_returns_woo_shape(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/orders/77.json",
                _FakeResponse(200, {"order": _sapo_order(id=77, financial_status="paid")}),
            )
        ]
    )
    _patch(monkeypatch, fake)
    woo = _client().get_order(77)
    assert woo["id"] == 77
    assert woo["financial_status"] == "paid"


def test_mark_order_paid_posts_sale_transaction_then_refetches(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "POST",
                "/admin/orders/55/transactions.json",
                _FakeResponse(200, {"transaction": {"id": 1, "kind": "sale"}}),
            ),
            (
                "GET",
                "/admin/orders/55.json",
                _FakeResponse(200, {"order": _sapo_order(id=55, financial_status="paid")}),
            ),
        ]
    )
    _patch(monkeypatch, fake)
    woo = _client().mark_order_paid(55, amount="409.94")
    # The transaction body marks a full paid sale recorded from the Hub.
    body = fake.sent("POST", "/admin/orders/55/transactions.json")[0]["json"]
    assert body["transaction"]["kind"] == "sale"
    assert body["transaction"]["amount"] == "409.94"
    assert body["transaction"]["status"] == "success"
    assert body["transaction"]["source_name"] == "web"
    # Re-GETs the order (transactions endpoint returns the txn, not the order).
    assert len(fake.sent("GET", "/admin/orders/55.json")) == 1
    assert woo["financial_status"] == "paid"


def test_list_products_maps_to_woo_shape(monkeypatch):
    fake = _FakeHttp(
        routes=[
            (
                "GET",
                "/admin/products.json",
                _FakeResponse(
                    200,
                    {
                        "products": [
                            {
                                "id": 11,
                                "name": "Tấm Pin 450W",
                                # Sapo sends a default option even for a simple
                                # (single-variant) product.
                                "options": [{"name": "Tiêu đề"}],
                                "variants": [{"sku": "PIN-450"}],
                            },
                            {
                                "id": 12,
                                "name": "Combo",
                                "options": [{"name": "Màu"}],
                                "variants": [{"sku": "C-1"}, {"sku": "C-2"}],
                            },
                        ]
                    },
                ),
            )
        ]
    )
    _patch(monkeypatch, fake)
    # Single variant → simple (despite the default option); >1 variant → variable.
    assert _client().list_products() == [
        {"id": 11, "name": "Tấm Pin 450W", "sku": "PIN-450", "type": "simple"},
        {"id": 12, "name": "Combo", "sku": "C-1", "type": "variable"},
    ]
