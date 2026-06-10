"""Health endpoint — proves the stack is wired (DB + Redis reachable)."""

from datetime import date, timedelta

from django.db import connection
from django.db.models import Count, F, OuterRef, Subquery, Sum
from django.db.models.functions import TruncDate
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import MasterProduct
from apps.monitoring.models import HealthCheck
from apps.orders.models import Order
from apps.sites.models import Site
from config.celery import app as celery_app


def _db_ok() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        return False


def _redis_ok() -> bool:
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1)
        conn.release()
        return True
    except Exception:
        return False


class HealthView(APIView):
    """GET /api/health/ → liveness (always 200) + readiness booleans.

    No authentication: a health check must not touch the DB (SessionAuth would),
    so it can still report ``db: false`` when Postgres is down instead of 500ing.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "db": _db_ok(), "redis": _redis_ok()})


def _pct_change(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _parse_period(request):
    today = date.today()
    default_from = today.replace(day=1)
    default_to = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    raw_from = request.query_params.get("date_from")
    raw_to = request.query_params.get("date_to")

    try:
        date_from = date.fromisoformat(raw_from) if raw_from else default_from
    except ValueError:
        date_from = default_from

    try:
        date_to = date.fromisoformat(raw_to) if raw_to else default_to
    except ValueError:
        date_to = default_to

    return date_from, date_to


STATUS_LABEL = {
    "completed": "Hoàn thành",
    "processing": "Đang xử lý",
    "cancelled": "Đã hủy",
    "on-hold": "Tạm giữ",
    "pending": "Chờ thanh toán",
    "refunded": "Đã hoàn tiền",
    "failed": "Thất bại",
}

HC_STATUS_LABEL = {
    "healthy": "Hoạt động",
    "warning": "Cảnh báo",
    "critical": "Ngừng hoạt động",
}

SITE_TYPE_LABEL = {
    "website": "Website",
    "api": "API",
    "mail": "Mail Server",
    "database": "Database",
}


class DashboardView(APIView):
    """GET /api/dashboard/ — aggregated metrics for the admin dashboard.

    Query params:
        date_from  ISO date (default: first day of current month)
        date_to    ISO date (default: last day of current month)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        date_from, date_to = _parse_period(request)

        # Previous period (same duration, immediately before)
        period_days = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_days - 1)

        orders_qs = Order.objects.filter(date_created_woo__date__range=(date_from, date_to))
        prev_qs = Order.objects.filter(date_created_woo__date__range=(prev_from, prev_to))

        # ── Stats ──────────────────────────────────────────────────────────────
        total_orders = orders_qs.count()
        prev_orders = prev_qs.count()

        revenue = float(orders_qs.aggregate(r=Sum("total"))["r"] or 0)
        prev_revenue = float(prev_qs.aggregate(r=Sum("total"))["r"] or 0)

        customers = (
            orders_qs.exclude(customer_email="")
            .values("customer_email")
            .distinct()
            .count()
        )
        prev_customers = (
            prev_qs.exclude(customer_email="")
            .values("customer_email")
            .distinct()
            .count()
        )

        products_total = MasterProduct.objects.filter(is_deleted=False).count()

        stats = {
            "orders": {"total": total_orders, "change_pct": _pct_change(total_orders, prev_orders)},
            "revenue": {"total": revenue, "change_pct": _pct_change(revenue, prev_revenue)},
            "customers": {"total": customers, "change_pct": _pct_change(customers, prev_customers)},
            "products": {"total": products_total, "change_pct": None},
        }

        # ── Orders chart (by day) ──────────────────────────────────────────────
        chart_rows = (
            orders_qs
            .annotate(day=TruncDate("date_created_woo"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        orders_chart = [
            {"date": row["day"].isoformat(), "count": row["count"]}
            for row in chart_rows
        ]

        # ── Orders summary (by status) ─────────────────────────────────────────
        by_status_rows = orders_qs.values("status").annotate(count=Count("id"))
        by_status_map = {row["status"]: row["count"] for row in by_status_rows}

        def _status_entry(key):
            count = by_status_map.get(key, 0)
            pct = round(count / total_orders * 100, 1) if total_orders else 0
            return {"count": count, "pct": pct, "label": STATUS_LABEL.get(key, key)}

        orders_summary = {
            "total": total_orders,
            "completed": _status_entry("completed"),
            "processing": _status_entry("processing"),
            "cancelled": _status_entry("cancelled"),
        }

        # ── Recent orders (last 10) ────────────────────────────────────────────
        recent_orders = []
        for o in Order.objects.select_related("site").order_by("-date_created_woo")[:10]:
            recent_orders.append({
                "id": o.id,
                "woo_order_id": o.woo_order_id,
                "number": o.number or str(o.woo_order_id),
                "customer_name": o.customer_name,
                "total": str(o.total),
                "status": o.status,
                "date_created_woo": o.date_created_woo.isoformat(),
                "site_name": o.site.name,
            })

        # ── Site health ────────────────────────────────────────────────────────
        latest_hc_status = (
            HealthCheck.objects.filter(site=OuterRef("pk"))
            .order_by("-checked_at")
            .values("status")[:1]
        )
        latest_hc_time = (
            HealthCheck.objects.filter(site=OuterRef("pk"))
            .order_by("-checked_at")
            .values("checked_at")[:1]
        )
        latest_hc_response = (
            HealthCheck.objects.filter(site=OuterRef("pk"))
            .order_by("-checked_at")
            .values("response_time_ms")[:1]
        )

        # All sites for counting totals; top 10 by most-recently-checked for table.
        sites_qs = (
            Site.objects.filter(is_deleted=False)
            .annotate(
                hc_status=Subquery(latest_hc_status),
                hc_checked_at=Subquery(latest_hc_time),
                hc_response_time=Subquery(latest_hc_response),
            )
            .order_by(F("hc_checked_at").desc(nulls_last=True), "name")
        )

        site_list = []
        up_count = warning_count = down_count = 0
        for s in sites_qs:
            hc = s.hc_status or ""
            if hc == "healthy":
                up_count += 1
                display_status = "healthy"
            elif hc == "warning":
                warning_count += 1
                display_status = "warning"
            elif hc == "critical":
                down_count += 1
                display_status = "critical"
            else:
                # Fall back to Site.status
                if s.status == "up":
                    up_count += 1
                    display_status = "healthy"
                elif s.status == "down":
                    down_count += 1
                    display_status = "critical"
                else:
                    display_status = "unknown"

            site_list.append({
                "id": s.id,
                "name": s.name,
                "site_type": s.site_type,
                "site_type_label": SITE_TYPE_LABEL.get(s.site_type, s.site_type),
                "status": display_status,
                "status_label": HC_STATUS_LABEL.get(display_status, "Chưa kiểm tra"),
                "hc_checked_at": s.hc_checked_at.isoformat() if s.hc_checked_at else None,
                "hc_response_time": s.hc_response_time,
            })

        site_health = {
            "total": len(site_list),
            "up": up_count,
            "warning": warning_count,
            "down": down_count,
            "sites": site_list[:10],  # top-10 most recently checked for the table
        }

        # ── Notifications (derived from recent health checks) ──────────────────
        notifications = []
        seen_sites = set()
        recent_hc = (
            HealthCheck.objects.select_related("site")
            .order_by("-checked_at")[:30]
        )

        for hc in recent_hc:
            site_id = hc.site_id
            if site_id in seen_sites:
                continue
            seen_sites.add(site_id)

            if hc.status == HealthCheck.Status.WARNING:
                ms = hc.response_time_ms
                time_str = f"{ms / 1000:.1f}s" if ms else "chậm"
                notifications.append({
                    "type": "warning",
                    "title": f"Phản hồi chậm: {hc.site.name}",
                    "message": f"Thời gian phản hồi cao hơn ngưỡng cho phép ({time_str}).",
                    "time": hc.checked_at.isoformat(),
                })
            elif hc.status == HealthCheck.Status.CRITICAL:
                notifications.append({
                    "type": "error",
                    "title": f"Lỗi kết nối: {hc.site.name}",
                    "message": hc.detail or "Không thể kết nối đến hệ thống.",
                    "time": hc.checked_at.isoformat(),
                })
            elif hc.status == HealthCheck.Status.HEALTHY:
                notifications.append({
                    "type": "success",
                    "title": f"Kiểm tra thành công: {hc.site.name}",
                    "message": "Hệ thống đang hoạt động bình thường.",
                    "time": hc.checked_at.isoformat(),
                })

            if len(notifications) >= 8:
                break

        return Response({
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            },
            "stats": stats,
            "orders_chart": orders_chart,
            "orders_summary": orders_summary,
            "recent_orders": recent_orders,
            "site_health": site_health,
            "notifications": notifications,
        })
