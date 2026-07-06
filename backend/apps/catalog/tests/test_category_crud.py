"""Hub-side category CRUD (create/rename/move-parent/soft-delete) over the API.

Categories used to be read-only (pull-from-site only); these cover the write
surface that builds the parent–child tree on the Hub itself.
"""

import pytest

from apps.catalog.models import Category

from .factories import CategoryFactory, MasterProductFactory


@pytest.mark.django_db
def test_create_root_category(client):
    resp = client.post(
        "/api/products/categories/",
        {"name": "  Pin  mặt trời  ", "slug": "pin"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    # Name is normalized (trim + collapse whitespace, case preserved).
    assert resp.data["name"] == "Pin mặt trời"
    assert resp.data["parent"] is None
    cat = Category.objects.get(pk=resp.data["id"])
    assert cat.slug == "pin" and cat.is_deleted is False


@pytest.mark.django_db
def test_create_child_under_parent(client):
    parent = CategoryFactory(name="Nguồn điện")
    resp = client.post(
        "/api/products/categories/",
        {"name": "Inverter", "parent": parent.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["parent"] == parent.id
    assert Category.objects.get(pk=resp.data["id"]).parent_id == parent.id


@pytest.mark.django_db
def test_create_duplicate_live_name_rejected(client):
    CategoryFactory(name="Inverter")
    resp = client.post("/api/products/categories/", {"name": "Inverter"}, format="json")
    assert resp.status_code == 400
    assert "name" in resp.data


@pytest.mark.django_db
def test_create_revives_soft_deleted_name(client):
    """A name colliding only with a SOFT-DELETED row revives it (the DB UNIQUE on
    name spans deleted rows) — no duplicate row, same id comes back."""
    dead = CategoryFactory(name="Inverter", is_deleted=True, slug="old")
    resp = client.post(
        "/api/products/categories/",
        {"name": "Inverter", "slug": "new"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["id"] == dead.id
    dead.refresh_from_db()
    assert dead.is_deleted is False and dead.slug == "new"
    assert Category.objects.filter(name="Inverter").count() == 1


@pytest.mark.django_db
def test_update_rename_and_move_parent(client):
    root = CategoryFactory(name="Nguồn điện")
    child = CategoryFactory(name="Inverter")
    resp = client.patch(
        f"/api/products/categories/{child.id}/",
        {"name": "Bộ hòa lưới", "parent": root.id},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    child.refresh_from_db()
    assert child.name == "Bộ hòa lưới" and child.parent_id == root.id


@pytest.mark.django_db
def test_update_parent_to_self_rejected(client):
    cat = CategoryFactory(name="Inverter")
    resp = client.patch(f"/api/products/categories/{cat.id}/", {"parent": cat.id}, format="json")
    assert resp.status_code == 400
    assert "parent" in resp.data


@pytest.mark.django_db
def test_update_parent_to_descendant_rejected(client):
    """Moving a category under its own descendant would form a cycle."""
    root = CategoryFactory(name="A")
    mid = CategoryFactory(name="B", parent=root)
    leaf = CategoryFactory(name="C", parent=mid)
    resp = client.patch(f"/api/products/categories/{root.id}/", {"parent": leaf.id}, format="json")
    assert resp.status_code == 400
    assert "parent" in resp.data
    root.refresh_from_db()
    assert root.parent_id is None  # unchanged


@pytest.mark.django_db
def test_delete_soft_deletes_and_promotes_children(client):
    """Deleting a parent promotes its children to the grandparent (root here) so
    the tree stays connected; it is a soft-delete, not a hard delete."""
    parent = CategoryFactory(name="Nguồn điện")
    child = CategoryFactory(name="Inverter", parent=parent)
    resp = client.delete(f"/api/products/categories/{parent.id}/")
    assert resp.status_code == 204
    parent.refresh_from_db()
    child.refresh_from_db()
    assert parent.is_deleted is True  # still in the DB
    assert child.parent_id is None and child.is_deleted is False


@pytest.mark.django_db
def test_deleted_category_excluded_from_list(client):
    CategoryFactory(name="Sống")
    dead = CategoryFactory(name="Chết")
    client.delete(f"/api/products/categories/{dead.id}/")
    names = [c["name"] for c in client.get("/api/products/categories/").data["results"]]
    assert "Sống" in names and "Chết" not in names


@pytest.mark.django_db
def test_delete_category_used_by_product_still_allowed(client):
    """WooCommerce-like: a category a product references by name can still be
    deleted (the product keeps the name string; a re-pull can revive it)."""
    cat = CategoryFactory(name="Pin mặt trời")
    MasterProductFactory(sku="SP-1", categories=["Pin mặt trời"])
    resp = client.delete(f"/api/products/categories/{cat.id}/")
    assert resp.status_code == 204
    cat.refresh_from_db()
    assert cat.is_deleted is True


@pytest.mark.django_db
def test_create_requires_auth():
    from rest_framework.test import APIClient

    resp = APIClient().post("/api/products/categories/", {"name": "X"}, format="json")
    assert resp.status_code in (401, 403)
