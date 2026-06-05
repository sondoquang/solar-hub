"""Service layer for the sites app: view → service → model/WooClient.

Handles secret encryption and the on-demand connection test. Views/serializers
stay thin; all WooCommerce traffic goes through ``WooClient``.
"""

import logging

import httpx
import openpyxl
from django.utils import timezone

from apps.integrations.woocommerce import WooClient

from .crypto import decrypt_secret, encrypt_secret
from .models import Site

logger = logging.getLogger(__name__)

IMPORT_COLUMNS = ["name", "base_url", "consumer_key", "consumer_secret"]


def create_site(*, name: str, base_url: str, consumer_key: str, consumer_secret: str) -> Site:
    return Site.objects.create(
        name=name,
        base_url=base_url,
        consumer_key=consumer_key,
        consumer_secret_enc=encrypt_secret(consumer_secret),
    )


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


def import_sites_from_xlsx(file) -> dict:
    """Parse an uploaded .xlsx and bulk-create sites.

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
        if Site.objects.filter(base_url=data["base_url"]).exists():
            errors.append({"row": idx, "error": f"base_url đã tồn tại: {data['base_url']}"})
            continue
        create_site(**data)
        created += 1

    return {"created": created, "errors": errors}
