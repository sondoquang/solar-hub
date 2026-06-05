import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="alice",
        password="OldPass123!",
        email="alice@example.com",
        first_name="Alice",
        last_name="Nguyen",
    )


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.mark.django_db
def test_me_returns_profile_with_role(client, user):
    resp = client.get("/api/auth/me/")
    assert resp.status_code == 200
    assert resp.data == {
        "id": user.id,
        "username": "alice",
        "email": "alice@example.com",
        "full_name": "Alice Nguyen",
        "role": "Người dùng",
    }


@pytest.mark.django_db
def test_role_reflects_permission_flags(db):
    User = get_user_model()
    admin = User.objects.create_superuser(username="root", password="x")
    staff = User.objects.create_user(username="staff", password="x", is_staff=True)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    staff_client = APIClient()
    staff_client.force_authenticate(user=staff)

    assert admin_client.get("/api/auth/me/").data["role"] == "Quản trị viên"
    assert staff_client.get("/api/auth/me/").data["role"] == "Nhân viên"


@pytest.mark.django_db
def test_patch_me_updates_full_name_and_email(client, user):
    resp = client.patch(
        "/api/auth/me/",
        {"full_name": "Alice Tran", "email": "new@example.com"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["full_name"] == "Alice Tran"
    assert resp.data["email"] == "new@example.com"

    user.refresh_from_db()
    assert user.first_name == "Alice"
    assert user.last_name == "Tran"
    assert user.email == "new@example.com"


@pytest.mark.django_db
def test_change_password_success(client, user):
    resp = client.post(
        "/api/auth/change-password/",
        {"old_password": "OldPass123!", "new_password": "BrandNew456!"},
        format="json",
    )
    assert resp.status_code == 204
    user.refresh_from_db()
    assert user.check_password("BrandNew456!")


@pytest.mark.django_db
def test_change_password_wrong_old(client, user):
    resp = client.post(
        "/api/auth/change-password/",
        {"old_password": "wrong", "new_password": "BrandNew456!"},
        format="json",
    )
    assert resp.status_code == 400
    assert "old_password" in resp.data
    user.refresh_from_db()
    assert user.check_password("OldPass123!")


@pytest.mark.django_db
def test_change_password_too_weak(client, user):
    resp = client.post(
        "/api/auth/change-password/",
        {"old_password": "OldPass123!", "new_password": "123"},
        format="json",
    )
    assert resp.status_code == 400
    assert "new_password" in resp.data


@pytest.mark.django_db
def test_endpoints_require_auth():
    anon = APIClient()
    assert anon.get("/api/auth/me/").status_code == 401
    assert anon.patch("/api/auth/me/", {}, format="json").status_code == 401
    assert anon.post("/api/auth/change-password/", {}, format="json").status_code == 401
