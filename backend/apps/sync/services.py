"""Category-run report: group ``pull_categories`` SyncLog rows by ``run_id``.

One "run" = one user click of "sync categories" (one fan-out across sites).
Each site writes one SyncLog row stamped with the run_id and carrying a
snapshot in ``detail`` (site name/url/hosting + the per-category woo→hub list,
see ``apps.catalog.services.pull_categories_for_site``). This module rolls
those rows up for the report endpoints and builds the Excel export.
"""

from io import BytesIO

from django.db.models import Min
from django.utils import timezone

from .models import SyncLog

# Same value as apps.catalog.services.CATEGORY_OPERATION; redeclared to avoid
# importing the (heavy, httpx-bound) catalog service module at startup.
CATEGORY_OPERATION = "pull_categories"


def category_runs_queryset():
    """Grouped queryset of runs (newest first), one row per ``run_id``.

    Legacy rows written before run_id existed are excluded — they carry no
    category snapshot, so there is nothing to report.
    """
    return (
        SyncLog.objects.filter(operation=CATEGORY_OPERATION, run_id__isnull=False)
        .values("run_id")
        .annotate(started_at=Min("created_at"))
        .order_by("-started_at")
    )


def _rollup_status(logs) -> str:
    """All success → success, all error → error, mixed → partial."""
    statuses = {log.status for log in logs}
    if statuses == {SyncLog.Status.SUCCESS}:
        return SyncLog.Status.SUCCESS
    if statuses == {SyncLog.Status.ERROR}:
        return SyncLog.Status.ERROR
    return SyncLog.Status.PARTIAL


def _summary(run_id, started_at, logs) -> dict:
    return {
        "run_id": str(run_id),
        "started_at": started_at,
        "site_count": len(logs),
        "total_pulled": sum(int((log.detail or {}).get("pulled") or 0) for log in logs),
        "total_mapped": sum(int((log.detail or {}).get("mapped") or 0) for log in logs),
        "error_count": sum(1 for log in logs if log.status == SyncLog.Status.ERROR),
        "status": _rollup_status(logs),
    }


def summarize_runs(run_rows) -> list[dict]:
    """Roll the page's runs up in Python — bounded work (page_size × sites/run),
    and JSON-key aggregates in SQL would be fragile for the ``detail`` counts."""
    run_ids = [row["run_id"] for row in run_rows]
    logs_by_run: dict = {}
    for log in SyncLog.objects.filter(
        operation=CATEGORY_OPERATION, run_id__in=run_ids
    ):
        logs_by_run.setdefault(log.run_id, []).append(log)
    return [
        _summary(row["run_id"], row["started_at"], logs_by_run.get(row["run_id"], []))
        for row in run_rows
    ]


def _site_row(log) -> dict:
    """One per-site row, null-safe: ``site`` is SET_NULL on delete, so fall
    back to the snapshot taken into ``detail`` at pull time."""
    site = log.site
    detail = log.detail or {}
    hosting = site.hosting if site else None
    return {
        "site_id": site.id if site else None,
        "site_name": site.name if site else detail.get("site_name", ""),
        "site_url": site.base_url if site else detail.get("site_url", ""),
        "hosting": (
            (hosting.provider or hosting.name)
            if hosting
            else detail.get("hosting", "")
        ),
        "status": log.status,
        "error": log.error,
        "pulled": int(detail.get("pulled") or 0),
        "mapped": int(detail.get("mapped") or 0),
        "categories": detail.get("categories") or [],
        "created_at": log.created_at,
    }


def run_detail(run_id) -> dict | None:
    """Summary + per-site rows (incl. category snapshots) of one run, or None."""
    logs = list(
        SyncLog.objects.filter(operation=CATEGORY_OPERATION, run_id=run_id)
        .select_related("site__hosting")
        .order_by("created_at")
    )
    if not logs:
        return None
    summary = _summary(run_id, min(log.created_at for log in logs), logs)
    summary["sites"] = [_site_row(log) for log in logs]
    return summary


# --- Excel export -------------------------------------------------------------

_OVERVIEW_HEADERS = [
    "Site",
    "URL",
    "Hosting",
    "Trạng thái",
    "Số danh mục (Woo)",
    "Đã ánh xạ (Hub)",
    "Lỗi",
]
_DETAIL_HEADERS = [
    "Site",
    "Hosting",
    "Woo ID",
    "Tên danh mục (Woo)",
    "Hub ID",
    "Tên danh mục (Hub)",
]


def build_run_workbook(detail: dict) -> bytes:
    """Two-sheet .xlsx for one run: "Tổng quan" (one row per site) and a flat
    "Chi tiết" (one row per category per site — flat instead of per-site sheets
    to dodge the 31-char sheet-name limit and duplicate site names). In-memory
    via BytesIO: a run is at most a few thousand rows, same class of inline work
    as the existing CSV/PDF exports.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True)
    started = timezone.localtime(detail["started_at"]).strftime("%d/%m/%Y %H:%M:%S")

    wb = Workbook()
    overview = wb.active
    overview.title = "Tổng quan"
    overview.append(["Báo cáo đồng bộ danh mục"])
    overview["A1"].font = bold
    overview.append(["Thời gian đồng bộ", started])
    overview.append(["Mã lần đồng bộ", detail["run_id"]])
    overview.append([])
    overview.append(_OVERVIEW_HEADERS)
    for cell in overview[overview.max_row]:
        cell.font = bold
    for row in detail["sites"]:
        overview.append(
            [
                row["site_name"],
                row["site_url"],
                row["hosting"],
                row["status"],
                row["pulled"],
                row["mapped"],
                row["error"],
            ]
        )

    sheet = wb.create_sheet("Chi tiết")
    sheet.append([f"Thời gian đồng bộ: {started}"])
    sheet["A1"].font = bold
    sheet.append(_DETAIL_HEADERS)
    for cell in sheet[2]:
        cell.font = bold
    for row in detail["sites"]:
        for cat in row["categories"]:
            sheet.append(
                [
                    row["site_name"],
                    row["hosting"],
                    cat.get("woo_id"),
                    cat.get("woo_name"),
                    cat.get("hub_id"),
                    cat.get("hub_name"),
                ]
            )

    widths = {overview: [28, 36, 18, 12, 18, 16, 24], sheet: [28, 18, 10, 40, 10, 40]}
    for ws, cols in widths.items():
        for i, width in enumerate(cols, start=1):
            ws.column_dimensions[get_column_letter(i)].width = width

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run_export_filename(detail: dict) -> str:
    started = timezone.localtime(detail["started_at"]).strftime("%Y%m%d-%H%M%S")
    return f"bao-cao-danh-muc-{started}.xlsx"
