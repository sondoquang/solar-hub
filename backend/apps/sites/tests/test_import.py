import io

import openpyxl
import pytest

from apps.sites.crypto import decrypt_secret
from apps.sites.models import Hosting, Site

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


# --- Hosting import ----------------------------------------------------------

HOSTING_HEADER = ("name", "provider", "account_username", "note", "check_concurrency")


@pytest.mark.django_db
def test_import_hostings_creates_with_concurrency(client):
    buf = make_xlsx(
        [
            ("TenTen A", "TenTen", "user_a", "note a", 3),
            ("TenTen B", "TenTen", "user_b", "", ""),  # blank concurrency -> default 5
        ],
        header=HOSTING_HEADER,
    )
    resp = client.post("/api/hostings/import_excel/", {"file": buf}, format="multipart")
    assert resp.status_code == 200
    assert resp.data["created"] == 2
    assert resp.data["errors"] == []
    assert Hosting.objects.get(name="TenTen A").check_concurrency == 3
    assert Hosting.objects.get(name="TenTen B").check_concurrency == 5


@pytest.mark.django_db
def test_import_hostings_skips_missing_name_and_duplicates(client):
    Hosting.objects.create(name="Dup", account_username="acc")
    buf = make_xlsx(
        [
            ("Good", "TenTen", "acc1", "", 5),
            ("", "TenTen", "acc2", "", 5),  # missing name
            ("Dup", "TenTen", "acc", "", 5),  # duplicate (name, account)
        ],
        header=HOSTING_HEADER,
    )
    resp = client.post("/api/hostings/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 1
    assert len(resp.data["errors"]) == 2


@pytest.mark.django_db
def test_import_hostings_missing_name_column(client):
    buf = make_xlsx([("TenTen",)], header=("provider",))
    resp = client.post("/api/hostings/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 0
    assert "Thiếu cột" in resp.data["errors"][0]["error"]


@pytest.mark.django_db
def test_import_hostings_only_name_column(client):
    buf = make_xlsx([("Solo",)], header=("name",))
    resp = client.post("/api/hostings/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 1
    h = Hosting.objects.get(name="Solo")
    assert h.check_concurrency == 5
    assert h.provider == ""


@pytest.mark.django_db
def test_import_hostings_invalid_concurrency_falls_back(client):
    buf = make_xlsx([("Bad", "", "", "", "abc")], header=HOSTING_HEADER)
    resp = client.post("/api/hostings/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 1
    assert Hosting.objects.get(name="Bad").check_concurrency == 5
