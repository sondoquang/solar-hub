import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_list_requires_view_user(plain_client, perm_client):
    assert plain_client.get("/api/auth/users/").status_code == 403
    assert perm_client("view_user").get("/api/auth/users/").status_code == 200


def test_create_user_with_password_and_groups(perm_client):
    group = Group.objects.create(name="Test nhóm")
    resp = perm_client("add_user").post(
        "/api/auth/users/",
        {
            "username": "newbie",
            "password": "StrongPass123!",
            "email": "n@example.com",
            "full_name": "Trần Bình",
            "group_ids": [group.id],
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["username"] == "newbie"
    assert resp.data["groups"] == [{"id": group.id, "name": "Test nhóm"}]
    user = User.objects.get(username="newbie")
    assert user.check_password("StrongPass123!")
    assert user.first_name == "Trần"
    assert user.last_name == "Bình"


def test_create_duplicate_username_400(perm_client):
    User.objects.create_user(username="dupe", password="x")
    resp = perm_client("add_user").post(
        "/api/auth/users/",
        {"username": "dupe", "password": "StrongPass123!"},
        format="json",
    )
    assert resp.status_code == 400
    assert "username" in resp.data


def test_create_weak_password_400(perm_client):
    resp = perm_client("add_user").post(
        "/api/auth/users/", {"username": "weakpw", "password": "123"}, format="json"
    )
    assert resp.status_code == 400
    assert "password" in resp.data


def test_patch_updates_profile_and_groups(perm_client):
    target = User.objects.create_user(username="target", password="x")
    group = Group.objects.create(name="Nhóm A")
    resp = perm_client("change_user").patch(
        f"/api/auth/users/{target.id}/",
        {"full_name": "Lê Văn C", "group_ids": [group.id]},
        format="json",
    )
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.first_name == "Lê"
    assert target.last_name == "Văn C"
    assert list(target.groups.all()) == [group]


def test_delete_deactivates_and_keeps_row(perm_client):
    target = User.objects.create_user(username="bye", password="x")
    resp = perm_client("delete_user").delete(f"/api/auth/users/{target.id}/")
    assert resp.status_code == 204
    target.refresh_from_db()  # row survives (audit FKs)
    assert target.is_active is False


def test_cannot_deactivate_self(perm_client):
    client = perm_client("delete_user", "view_user")
    resp = client.delete(f"/api/auth/users/{client.user.id}/")
    assert resp.status_code == 400
    client.user.refresh_from_db()
    assert client.user.is_active is True


def test_activate(perm_client):
    target = User.objects.create_user(username="off", password="x", is_active=False)
    resp = perm_client("change_user").post(f"/api/auth/users/{target.id}/activate/")
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.is_active is True


def test_set_password_validates(perm_client):
    target = User.objects.create_user(username="pwreset", password="OldOne123!")
    client = perm_client("change_user")
    ok = client.post(
        f"/api/auth/users/{target.id}/set_password/",
        {"password": "BrandNew456!"},
        format="json",
    )
    assert ok.status_code == 204
    target.refresh_from_db()
    assert target.check_password("BrandNew456!")

    weak = client.post(
        f"/api/auth/users/{target.id}/set_password/",
        {"password": "123"},
        format="json",
    )
    assert weak.status_code == 400
