import io

import openpyxl
import pytest

from apps.sites.crypto import decrypt_secret
from apps.sites.models import Site

from .factories import HostingFactory


def make_xlsx(rows, header=("name", "base_url", "consumer_key", "consumer_secret")):
    wb = openpyxl.Workbook()
    ws = wb.active
    if header:
        ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "sites.xlsx"
    return buf


@pytest.mark.django_db
def test_import_creates_sites_and_encrypts(client):
    buf = make_xlsx(
        [
            ("Shop A", "https://a.example.com", "ck_a", "cs_a"),
            ("Shop B", "https://b.example.com", "ck_b", "cs_b"),
        ]
    )
    resp = client.post("/api/sites/import_excel/", {"file": buf}, format="multipart")
    assert resp.status_code == 200
    assert resp.data["created"] == 2
    assert resp.data["errors"] == []
    assert Site.objects.count() == 2
    a = Site.objects.get(name="Shop A")
    assert decrypt_secret(a.consumer_secret_enc) == "cs_a"


@pytest.mark.django_db
def test_import_reports_row_errors_and_duplicates(client):
    Site.objects.create(
        name="Existing", base_url="https://dup.example.com",
        consumer_key="ck", consumer_secret_enc=b"x",
    )
    buf = make_xlsx(
        [
            ("Good", "https://good.example.com", "ck", "cs"),
            ("Missing secret", "https://m.example.com", "ck", ""),
            ("Dup", "https://dup.example.com", "ck", "cs"),
        ]
    )
    resp = client.post("/api/sites/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 1
    assert len(resp.data["errors"]) == 2


@pytest.mark.django_db
def test_import_missing_column(client):
    buf = make_xlsx([("x", "y")], header=("name", "base_url"))
    resp = client.post("/api/sites/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 0
    assert "Thiếu cột" in resp.data["errors"][0]["error"]


@pytest.mark.django_db
def test_import_assigns_chosen_hosting(client):
    hosting = HostingFactory()
    buf = make_xlsx([("Shop A", "https://a.example.com", "ck", "cs")])
    resp = client.post(
        "/api/sites/import_excel/",
        {"file": buf, "hosting": hosting.id},
        format="multipart",
    )
    assert resp.data["created"] == 1
    assert Site.objects.get(name="Shop A").hosting_id == hosting.id


@pytest.mark.django_db
def test_import_rejects_invalid_hosting(client):
    buf = make_xlsx([("Shop A", "https://a.example.com", "ck", "cs")])
    resp = client.post(
        "/api/sites/import_excel/",
        {"file": buf, "hosting": 999999},
        format="multipart",
    )
    assert resp.status_code == 400
    assert Site.objects.count() == 0
