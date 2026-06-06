"""Service layer for the monitoring app: view → service → model.

Owns the ``HealthCheck`` history (recording, filtering, aggregation, export).
The recording entry point ``record_check`` is called from
``apps/sites/services.test_connection`` so every connection test — manual or
periodic — leaves an audit row.
"""

import csv
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import HealthCheck

# Response-time thresholds (ms) used to derive the 3-level health status.
HEALTHY_MAX_MS = 1000  # < 1s  → khỏe mạnh
WARNING_MAX_MS = 5000  # 1–5s  → cảnh báo; ≥ 5s or unreachable → lỗi nghiêm trọng


def derive_status(ok: bool, response_time_ms: int | None) -> str:
    """Map reachability + response time to a 3-level health status."""
    if not ok:
        return HealthCheck.Status.CRITICAL
    if response_time_ms is not None and response_time_ms >= WARNING_MAX_MS:
        return HealthCheck.Status.CRITICAL
    if response_time_ms is not None and response_time_ms >= HEALTHY_MAX_MS:
        return HealthCheck.Status.WARNING
    return HealthCheck.Status.HEALTHY


def record_check(
    *,
    site,
    ok: bool,
    response_time_ms: int | None = None,
    detail: str = "",
    check_type: str = HealthCheck.CheckType.MANUAL,
    performed_by=None,
) -> HealthCheck:
    """Append one health-check row. ``performed_by`` is kept only for an
    authenticated user (the periodic task passes ``None`` → "Hệ thống")."""
    if check_type not in HealthCheck.CheckType.values:
        check_type = HealthCheck.CheckType.MANUAL
    if performed_by is not None and not getattr(
        performed_by, "is_authenticated", False
    ):
        performed_by = None
    return HealthCheck.objects.create(
        site=site,
        status=derive_status(ok, response_time_ms),
        check_type=check_type,
        response_time_ms=response_time_ms,
        ok=ok,
        detail=detail[:255],
        performed_by=performed_by,
        checked_at=timezone.now(),
    )


# --- Querying / aggregation --------------------------------------------------


def filter_health_checks(qs, params):
    """Apply the list-screen filters (status / site / hosting / date range)."""
    status = params.get("status")
    if status in HealthCheck.Status.values:
        qs = qs.filter(status=status)

    check_type = params.get("check_type")
    if check_type in HealthCheck.CheckType.values:
        qs = qs.filter(check_type=check_type)

    site = params.get("site")
    if site:
        qs = qs.filter(site_id=site)

    hosting = params.get("hosting")
    if hosting == "none":
        qs = qs.filter(site__hosting__isnull=True)
    elif hosting:
        qs = qs.filter(site__hosting_id=hosting)

    date_from = parse_date(params.get("date_from") or "")
    if date_from:
        qs = qs.filter(checked_at__date__gte=date_from)
    date_to = parse_date(params.get("date_to") or "")
    if date_to:
        qs = qs.filter(checked_at__date__lte=date_to)

    return qs


def _status_counts(qs) -> dict:
    counts = {s: 0 for s in HealthCheck.Status.values}
    # .order_by() clears the model's Meta ordering — otherwise ``checked_at``
    # leaks into the GROUP BY and the per-status counts come out wrong.
    for row in qs.order_by().values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]
    return counts


def health_stats(qs, params) -> dict:
    """Counts per status for the filtered range, plus a vs-previous-period
    percentage change for the total (only when an explicit date range is set)."""
    counts = _status_counts(qs)
    total = sum(counts.values())
    stats = {
        "total": total,
        "healthy": counts[HealthCheck.Status.HEALTHY],
        "warning": counts[HealthCheck.Status.WARNING],
        "critical": counts[HealthCheck.Status.CRITICAL],
        "trend_pct": _total_trend_pct(params, total),
    }
    return stats


def _total_trend_pct(params, current_total: int):
    """Percent change of total checks vs the immediately preceding window of the
    same length. Returns ``None`` when no full date range is provided."""
    date_from = parse_date(params.get("date_from") or "")
    date_to = parse_date(params.get("date_to") or "")
    if not (date_from and date_to) or date_to < date_from:
        return None
    span = date_to - date_from + timedelta(days=1)
    prev_from = date_from - span
    prev_to = date_from - timedelta(days=1)
    prev_total = HealthCheck.objects.filter(
        checked_at__date__gte=prev_from, checked_at__date__lte=prev_to
    ).count()
    if prev_total == 0:
        return None
    return round((current_total - prev_total) / prev_total * 100, 1)


# --- Export ------------------------------------------------------------------

EXPORT_HEADERS = [
    "STT",
    "Website",
    "Base URL",
    "Hosting",
    "Loại kiểm tra",
    "Thời gian kiểm tra",
    "Trạng thái",
    "Thời gian phản hồi (ms)",
    "Người thực hiện",
]


def _performed_by_name(check: HealthCheck) -> str:
    if check.performed_by is None:
        return "Hệ thống"
    return check.performed_by.get_full_name() or check.performed_by.get_username()


def _export_row(i: int, check: HealthCheck) -> list:
    return [
        i,
        check.site.name,
        check.site.base_url,
        check.site.hosting.name if check.site.hosting else "",
        check.get_check_type_display(),
        timezone.localtime(check.checked_at).strftime("%Y-%m-%d %H:%M:%S"),
        check.get_status_display(),
        check.response_time_ms if check.response_time_ms is not None else "",
        _performed_by_name(check),
    ]


class _LineWriter:
    """A file-like sink that returns each written line (for streaming CSV)."""

    def write(self, value):
        return value


def stream_health_checks_csv(qs):
    """Yield the filtered rows as CSV lines (UTF-8 BOM first so Excel renders
    Vietnamese). Uses ``.iterator()`` so large reports stream, not buffer."""
    writer = csv.writer(_LineWriter())
    yield "﻿" + writer.writerow(EXPORT_HEADERS)
    for i, check in enumerate(qs.iterator(), start=1):
        yield writer.writerow(_export_row(i, check))
