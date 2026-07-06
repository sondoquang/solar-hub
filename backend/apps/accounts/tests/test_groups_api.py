import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

pytestmark = pytest.mark.django_db


def _perm_id(codename):
    return Permission.objects.get(codename=codename).id


def test_requires_perms(plain_client):
    assert plain_client.get("/api/auth/groups/").status_code == 403
    assert plain_client.get("/api/auth/permissions/").status_code == 403


def test_group_crud_roundtrip(admin_client):
    wanted = sorted([_perm_id("view_order"), _perm_id("forward_order")])
    resp = admin_client.post(
        "/api/auth/groups/",
        {"name": "Vận hành", "permission_ids": wanted},
        format="json",
    )
    assert resp.status_code == 201
    gid = resp.data["id"]
    assert sorted(resp.data["permission_ids"]) == wanted
    assert resp.data["permission_count"] == 2
    assert resp.data["user_count"] == 0

    resp = admin_client.patch(
        f"/api/auth/groups/{gid}/",
        {"permission_ids": [_perm_id("view_order")]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["permission_ids"] == [_perm_id("view_order")]

    assert admin_client.delete(f"/api/auth/groups/{gid}/").status_code == 204


def test_duplicate_name_400(admin_client):
    Group.objects.create(name="Trùng tên")
    resp = admin_client.post(
        "/api/auth/groups/", {"name": "Trùng tên"}, format="json"
    )
    assert resp.status_code == 400


def test_non_curated_permission_rejected(admin_client):
    stray = Permission.objects.get(
        codename="add_logentry", content_type__app_label="admin"
    )
    resp = admin_client.post(
        "/api/auth/groups/",
        {"name": "Nhóm lậu", "permission_ids": [stray.id]},
        format="json",
    )
    assert resp.status_code == 400


def test_delete_group_with_members_blocked(admin_client):
    group = Group.objects.create(name="Đang có người")
    user = get_user_model().objects.create_user(username="member", password="x")
    user.groups.add(group)
    resp = admin_client.delete(f"/api/auth/groups/{group.id}/")
    assert resp.status_code == 400
    assert Group.objects.filter(id=group.id).exists()


def test_permission_catalog_shape(perm_client):
    resp = perm_client("view_group").get("/api/auth/permissions/")
    assert resp.status_code == 200
    modules = {m["module"]: m for m in resp.data}

    # Full-CRUD module: 4 standard actions (VN labels) + the 3 custom perms.
    order_perms = modules["orders"]["models"][0]["permissions"]
    assert [p["label"] for p in order_perms[:4]] == ["Xem", "Thêm", "Sửa", "Xóa"]
    customs = {p["codename"] for p in order_perms if p["is_custom"]}
    assert customs == {"sync_order", "forward_order", "email_order"}

    # Read-only module: only view + the custom refresh perm.
    domain_perms = modules["domains"]["models"][0]["permissions"]
    assert {p["codename"] for p in domain_perms} == {
        "view_domaininfo",
        "refresh_domaininfo",
    }

    # Internal models never leak into the matrix.
    all_models = {m["model"] for mod in resp.data for m in mod["models"]}
    assert "productimage" not in all_models
    assert "logentry" not in all_models
    assert "productmapping" not in all_models
