"""Service layer for the sites app: view → service → model/WooClient.

Handles secret encryption and the on-demand connection test. Views/serializers
stay thin; all WooCommerce traffic goes through ``WooClient``.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
import openpyxl
from django.db import connection
from django.utils import timezone

from apps.integrations.woocommerce import WooClient

from .crypto import decrypt_secret, encrypt_secret
from .models import Hosting, Site

logger = logging.getLogger(__name__)

IMPORT_COLUMNS = ["name", "base_url", "consumer_key", "consumer_secret"]

DEFAULT_CHECK_CONCURRENCY = 5


def create_site(
    *, name: str, base_url: str, consumer_key: str, consumer_secret: str, hosting=None
) -> Site:
    return Site.objects.create(
        name=name,
        base_url=base_url,
        consumer_key=consumer_key,
        consumer_secret_enc=encrypt_secret(consumer_secret),
        hosting=hosting,
    )


def delete_site(site: Site) -> None:
    site.is_deleted = True
    site.deleted_at = timezone.now()
    site.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


def update_site(site: Site, *, consumer_secret: str | None = None, **fields) -> Site:
    for attr, value in fields.items():
        setattr(site, attr, value)
    if consumer_secret:
        site.consumer_secret_enc = encrypt_secret(consumer_secret)
    site.save()
    return site


def client_for_site(site: Site) -> WooClient:
    """Build a WooClient with the decrypted secret (in memory only)."""
    return WooClient(
        base_url=site.base_url,
        consumer_key=site.consumer_key,
        consumer_secret=decrypt_secret(site.consumer_secret_enc),
    )


def test_connection(site: Site) -> dict:
    """Call system_status to verify the key. Updates Site.status, returns a result dict."""
    ok = False
    detail = ""
    try:
        client_for_site(site).system_status()
        ok = True
        detail = "Kết nối thành công."
    except httpx.HTTPError as exc:
        detail = f"Lỗi kết nối: {exc.__class__.__name__}"
        logger.error("test_connection failed site_id=%s: %s", site.id, exc)
    except Exception as exc:  # noqa: BLE001 — surface as down, but log the cause
        detail = f"Lỗi không xác định: {exc.__class__.__name__}"
        logger.error("test_connection error site_id=%s: %s", site.id, exc)

    site.status = Site.Status.UP if ok else Site.Status.DOWN
    site.last_checked_at = timezone.now()
    site.save(update_fields=["status", "last_checked_at", "updated_at"])
    return {"ok": ok, "status": site.status, "detail": detail}


def bulk_test_connections(sites) -> list[dict]:
    """Test a list of sites sequentially (one at a time = natural throttle)."""
    return [{"id": s.id, **test_connection(s)} for s in sites]


# --- Hosting -----------------------------------------------------------------


def create_hosting(*, name: str, **fields) -> Hosting:
    return Hosting.objects.create(name=name, **fields)


def update_hosting(hosting: Hosting, **fields) -> Hosting:
    for attr, value in fields.items():
        setattr(hosting, attr, value)
    hosting.save()
    return hosting


def delete_hosting(hosting: Hosting) -> None:
    """Soft-delete a hosting. Member sites keep their FK (the hosting is just
    hidden), so re-grouping is reversible by un-deleting it."""
    hosting.is_deleted = True
    hosting.deleted_at = timezone.now()
    hosting.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


def _check_site_threadsafe(site: Site) -> dict:
    try:
        return {"id": site.id, **test_connection(site)}
    finally:
        # Each worker thread opens its own (thread-local) DB connection; close it
        # so the pool does not leak connections every health-check round.
        connection.close()


def check_hosting(hosting_id) -> list[dict]:
    """Health-check every site of one hosting, at most ``check_concurrency``
    domains at a time (the rest queue and run as slots free up). Different
    hostings are checked in parallel by the Celery fan-out in
    apps/monitoring/tasks.py. ``hosting_id=None`` checks sites with no hosting."""
    sites = list(Site.objects.filter(hosting_id=hosting_id, is_deleted=False))
    if not sites:
        return []

    concurrency = DEFAULT_CHECK_CONCURRENCY
    if hosting_id is not None:
        hosting = Hosting.objects.filter(id=hosting_id, is_deleted=False).first()
        if hosting:
            concurrency = max(1, hosting.check_concurrency)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(executor.map(_check_site_threadsafe, sites))


def import_sites_from_xlsx(file, hosting=None) -> dict:
    """Parse an uploaded .xlsx and bulk-create sites, optionally assigning every
    created site to ``hosting``.

    Expected header row: name, base_url, consumer_key, consumer_secret.
    Returns ``{"created": int, "errors": [{"row": int, "error": str}]}``.
    Rows missing required data or whose base_url already exists are skipped
    with an error entry (so partial imports surface clearly).
    """
    try:
        wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    except Exception:
        return {"created": 0, "errors": [{"row": 0, "error": "File không đọc được (.xlsx)."}]}

    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        return {"created": 0, "errors": [{"row": 0, "error": "File rỗng."}]}

    cols = {str(h).strip().lower(): i for i, h in enumerate(header) if h is not None}
    missing = [c for c in IMPORT_COLUMNS if c not in cols]
    if missing:
        return {"created": 0, "errors": [{"row": 1, "error": f"Thiếu cột: {', '.join(missing)}"}]}

    created = 0
    errors: list[dict] = []
    for idx, row in enumerate(rows, start=2):
        data = {}
        for col in IMPORT_COLUMNS:
            i = cols[col]
            value = row[i] if i < len(row) else None
            data[col] = str(value).strip() if value is not None else ""

        if not all(data.values()):
            errors.append({"row": idx, "error": "Thiếu dữ liệu bắt buộc."})
            continue
        if Site.objects.filter(base_url=data["base_url"], is_deleted=False).exists():
            errors.append({"row": idx, "error": f"base_url đã tồn tại: {data['base_url']}"})
            continue
        create_site(**data, hosting=hosting)
        created += 1

    return {"created": created, "errors": errors}
