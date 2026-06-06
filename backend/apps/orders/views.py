"""Orders API — read-only aggregated orders + a manual poll trigger.

- ``GET  /api/orders/``            — paginated list (search / filters / sort).
- ``GET  /api/orders/{id}/``       — one order (detail modal).
- ``GET  /api/orders/stats/``      — totals/revenue for the current filter.
- ``POST /api/orders/poll_now/``   — kick the poll fan-out (the "Đồng bộ ngay" button).
- ``POST /api/orders/{id}/complete/`` — mark one order completed (pushes to WooCommerce).

Orders are pulled in by the periodic poll (apps/sync/tasks); the only write is
``complete``, which pushes a status change back to the site and re-syncs the Hub.
"""

import logging

import httpx
from django.utils.dateparse import parse_date
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from . import services
from .models import Order
from .serializers import OrderSerializer

logger = logging.getLogger(__name__)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["number", "customer_name", "customer_phone", "site__name"]
    ordering_fields = ["date_created_woo", "total", "status"]
    ordering = ["-date_created_woo"]

    def get_queryset(self):
        qs = Order.objects.select_related("site", "site__hosting")
        return services.list_orders_qs(qs, self.request.query_params)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Totals/revenue for the filtered range (cards), independent of paging."""
        qs = self.filter_queryset(self.get_queryset())
        return Response(services.order_stats(qs))

    @action(detail=False, methods=["post"])
    def poll_now(self, request):
        """Trigger an immediate poll of ONE status (async, via Celery).

        Body (all optional): ``status`` (default ``processing``; must be one of
        ``services.ALLOWED_POLL_STATUSES``), ``sites`` (list of site ids; the
        whole fleet when omitted), and ``date_from``/``date_to`` (``YYYY-MM-DD``;
        when given, the sync re-pulls orders *created* in that window instead of
        using the per-site watermark). One request syncs exactly one status.
        """
        from apps.sync.tasks import poll_all_orders

        status = request.data.get("status") or services.POLL_STATUS
        if status not in services.ALLOWED_POLL_STATUSES:
            return Response(
                {"detail": f"Trạng thái không hợp lệ: {status}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        sites = request.data.get("sites")
        if sites is not None:
            if not isinstance(sites, list) or not all(
                isinstance(s, int) for s in sites
            ):
                return Response(
                    {"detail": "sites phải là danh sách id (số nguyên)."},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )

        date_from = request.data.get("date_from") or None
        date_to = request.data.get("date_to") or None
        for label, value in (("date_from", date_from), ("date_to", date_to)):
            if value is not None and parse_date(value) is None:
                return Response(
                    {"detail": f"{label} không hợp lệ (định dạng YYYY-MM-DD)."},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )

        result = poll_all_orders.delay(
            status=status,
            site_ids=sites or None,
            date_from=date_from,
            date_to=date_to,
        )
        return Response({"task_id": result.id, "status": status})

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark this order ``completed`` on its WooCommerce site, then sync the Hub.

        Only orders currently ``processing`` can be completed (business rule).
        Synchronous (a single PUT, like the site connection test) so the UI gets
        the updated order back immediately. Errors are logged by id only (no PII).
        """
        order = self.get_object()
        try:
            order = services.mark_order_completed(order)
        except services.InvalidStatusTransition as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT
            )
        except httpx.HTTPError:
            logger.error(
                "complete order failed order_id=%s site_id=%s",
                order.id,
                order.site_id,
            )
            return Response(
                {"detail": "Không thể cập nhật đơn trên WooCommerce."},
                status=http_status.HTTP_502_BAD_GATEWAY,
            )
        return Response(self.get_serializer(order).data)
