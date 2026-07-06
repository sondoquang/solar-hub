"""Enforcement matrix for ``config.permissions.RBACPermission``."""

import pytest

pytestmark = pytest.mark.django_db


def test_list_orders_requires_view_order(plain_client, perm_client):
    assert plain_client.get("/api/orders/").status_code == 403
    assert perm_client("view_order").get("/api/orders/").status_code == 200


def test_write_requires_add_perm(perm_client):
    client = perm_client("view_site")
    assert client.get("/api/sites/").status_code == 200
    assert client.post("/api/sites/", {"name": "x"}, format="json").status_code == 403


def test_custom_action_requires_business_perm(perm_client):
    # view_order alone is NOT enough for the forward business action…
    assert perm_client("view_order").post("/api/orders/1/forward/").status_code == 403
    # …with forward_order the permission layer passes (404: no such order).
    assert (
        perm_client("forward_order").post("/api/orders/1/forward/").status_code == 404
    )


def test_superuser_bypasses_everything(admin_client):
    assert admin_client.get("/api/orders/").status_code == 200
    assert admin_client.get("/api/auth/users/").status_code == 200
    assert admin_client.get("/api/auth/permissions/").status_code == 200


def test_authenticated_only_endpoints_stay_open(plain_client):
    assert plain_client.get("/api/auth/me/").status_code == 200
    assert plain_client.get("/api/dashboard/").status_code == 200


def test_sync_runs_require_view_synclog(plain_client, perm_client):
    assert plain_client.get("/api/sync/category-runs/").status_code == 403
    assert (
        perm_client("view_synclog").get("/api/sync/category-runs/").status_code == 200
    )
    assert plain_client.get("/api/sync/product-runs/").status_code == 403


def test_mail_settings_perms(plain_client, perm_client):
    assert plain_client.get("/api/mail-settings/").status_code == 403
    assert perm_client("view_mailsettings").get("/api/mail-settings/").status_code == 200
    # Test email: 403 without the custom perm; with it the permission layer
    # passes (400 — SMTP is not configured in tests).
    assert (
        plain_client.post("/api/mail-settings/test/", {}, format="json").status_code
        == 403
    )
    resp = perm_client("test_mailsettings").post(
        "/api/mail-settings/test/", {}, format="json"
    )
    assert resp.status_code == 400
