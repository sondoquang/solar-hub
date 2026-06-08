"""Site-note history API tests.

Covers the journal behaviour (newest first, scoped per site), rich-text HTML
sanitization, image attachment add/remove, and soft-delete. Images are tiny
real PNGs (Pillow) wrapped in SimpleUploadedFile so the ImageField validates.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.sites.models import SiteNote, SiteNoteImage

from .factories import SiteFactory


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # Write uploads to a throwaway dir, not the repo's backend/media.
    settings.MEDIA_ROOT = str(tmp_path)


def make_image(name="a.png", fmt="PNG", content_type="image/png", size=(2, 2)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)


@pytest.mark.django_db
def test_create_note_with_images(client):
    site = SiteFactory()
    resp = client.post(
        "/api/site-notes/",
        {
            "site": site.id,
            "content": "<p>Ghi chú <strong>quan trọng</strong></p>",
            "images": [make_image("a.png"), make_image("b.png")],
        },
        format="multipart",
    )
    assert resp.status_code == 201
    assert len(resp.data["images"]) == 2
    assert resp.data["images"][0]["url"].startswith("http")
    # conftest authenticates as username "tester" (no full name set).
    assert resp.data["created_by_name"] == "tester"
    assert "<strong>" in resp.data["content"]


@pytest.mark.django_db
def test_create_note_sanitizes_html(client):
    site = SiteFactory()
    resp = client.post(
        "/api/site-notes/",
        {
            "site": site.id,
            "content": "<p>hi</p><script>alert(1)</script>",
        },
        format="multipart",
    )
    assert resp.status_code == 201
    assert "<script>" not in resp.data["content"]
    assert "alert" not in resp.data["content"]
    assert "<p>hi</p>" in resp.data["content"]


@pytest.mark.django_db
def test_list_is_newest_first_and_scoped_to_site(client):
    site = SiteFactory()
    other = SiteFactory()
    n1 = SiteNote.objects.create(site=site, content="<p>first</p>")
    n2 = SiteNote.objects.create(site=site, content="<p>second</p>")
    SiteNote.objects.create(site=other, content="<p>other</p>")

    resp = client.get("/api/site-notes/", {"site": site.id})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data["results"]]
    assert ids == [n2.id, n1.id]  # newest first


@pytest.mark.django_db
def test_update_adds_and_removes_images(client):
    site = SiteFactory()
    note = SiteNote.objects.create(site=site, content="<p>x</p>")
    img = SiteNoteImage.objects.create(
        note=note, image=make_image("old.png"), original_name="old.png"
    )

    resp = client.patch(
        f"/api/site-notes/{note.id}/",
        {
            "content": "<p>updated</p>",
            "images": [make_image("new.png")],
            "remove_image_ids": [img.id],
        },
        format="multipart",
    )
    assert resp.status_code == 200
    assert resp.data["content"] == "<p>updated</p>"
    names = [i["original_name"] for i in resp.data["images"]]
    assert names == ["new.png"]
    assert not SiteNoteImage.objects.filter(id=img.id).exists()


@pytest.mark.django_db
def test_delete_is_soft(client):
    site = SiteFactory()
    note = SiteNote.objects.create(site=site, content="<p>x</p>")
    resp = client.delete(f"/api/site-notes/{note.id}/")
    assert resp.status_code == 204
    note.refresh_from_db()
    assert note.is_deleted is True
    assert note.deleted_at is not None
    # Hidden from the list.
    resp = client.get("/api/site-notes/", {"site": site.id})
    assert resp.data["count"] == 0


@pytest.mark.django_db
def test_rejects_non_image_attachment(client):
    site = SiteFactory()
    bad = SimpleUploadedFile("note.txt", b"not an image", content_type="text/plain")
    resp = client.post(
        "/api/site-notes/",
        {"site": site.id, "content": "<p>x</p>", "images": [bad]},
        format="multipart",
    )
    assert resp.status_code == 400
    # Nothing persisted (atomic create rolled back).
    assert SiteNote.objects.count() == 0


@pytest.mark.django_db
def test_requires_authentication():
    from rest_framework.test import APIClient

    site = SiteFactory()
    resp = APIClient().get("/api/site-notes/", {"site": site.id})
    assert resp.status_code in (401, 403)
