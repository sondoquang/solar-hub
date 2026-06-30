"""Orders API — read-only aggregated orders + a manual poll trigger.

- ``GET  /api/orders/``            — paginated list (search / filters / sort).
- ``GET  /api/orders/{id}/``       — one order (detail modal).
- ``GET  /api/orders/stats/``      — totals/revenue for the current filter.
- ``POST /api/orders/poll_now/``   — kick the poll fan-out (the "Đồng bộ ngay" button).
- ``POST /api/orders/{id}/complete/`` — mark one order completed (pushes to WooCommerce).
- ``POST /api/orders/{id}/cancel/``   — cancel one order (pushes to WooCommerce/Sapo).
- ``POST /api/orders/{id}/mark_paid/``— mark one Sapo order paid (records a Sapo transaction).
- ``POST /api/orders/{id}/forward/``  — forward one order to marketing (Hub-internal, one-way).
- ``POST /api/orders/forward_bulk/``  — forward many selected orders to marketing at once.
- ``POST /api/orders/send_email/``    — email selected orders to one address (HTML + PDF).

Orders are pulled in by the periodic poll (apps/sync/tasks). ``complete``/``cancel``
push a status change back to the site and re-sync the Hub; ``forward``/``forward_bulk``
only flip the Hub-internal marketing flag (no WooCommerce traffic, never reverted).
"""

import logging

import httpx
from django.utils.dateparse import parse_date
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.sites.models import Site

from . import services
from .models import Order
from .serializers import OrderSerializer

logger = logging.getLogger(__name__)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["number", "customer_name", "customer_phone", "site__name"]
    ordering_fields = ["date_created_woo", "total", "status", "risk_score"]
    ordering = ["-date_created_woo"]

    def get_queryset(self):
        qs = Order.objects.select_related("site", "site__hosting")
        return services.list_orders_qs(qs, self.request.query_params)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Totals/revenue for the filtered range (cards), independent of paging."""
        qs = self.filter_queryset(self.get_queryset())
        return Response(services.order_stats(qs))

    @action(detail=False, methods=["get"])
    def export_pdf(self, request):
        """Stream the selected orders as a single PDF (one order per page).

        ``?ids=1,2,3`` restricts to those orders (the "Xuất PDF" of ticked rows
        or one order from the detail modal); without it the whole filtered
        selection is exported. Capped at ``services.MAX_PDF_ORDERS``.
        """
        from django.http import HttpResponse

        from .pdf import build_orders_pdf

        qs = self.filter_queryset(self.get_queryset())
        orders = services.select_orders_for_pdf(qs, request.query_params.get("ids"))
        pdf_bytes = build_orders_pdf(orders)

        filename = (
            f"don-hang-{orders[0].number}.pdf"
            if len(orders) == 1
            else "don-hang.pdf"
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=["post"])
    def send_email(self, request):
        """Email the selected orders to one address (HTML body + PDF attachment).

        Body: ``{"recipient": "a@b.com", "ids": [1, 2, 3]}``. The ids are
        intersected with the current filtered queryset (filters/permissions still
        apply). Synchronous — like ``complete``/``cancel`` it does one external
        I/O call and returns the result so the UI can confirm. SMTP errors map to
        502; a misconfigured account maps to 400. Errors carry no PII.
        """
        import smtplib

        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        from apps.mailer import services as mailer_services

        recipient = (request.data.get("recipient") or "").strip()
        try:
            validate_email(recipient)
        except ValidationError:
            return Response(
                {"detail": "Email người nhận không hợp lệ."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids or not all(
            isinstance(i, int) for i in ids
        ):
            return Response(
                {"detail": "ids phải là danh sách id (số nguyên) và không rỗng."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        qs = self.filter_queryset(self.get_queryset())
        orders = services.select_orders_for_pdf(qs, ",".join(str(i) for i in ids))
        if not orders:
            return Response(
                {"detail": "Không có đơn hàng để gửi."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        try:
            sent = mailer_services.send_orders_email(
                orders, [recipient], title="Đơn hàng gửi thủ công"
            )
        except mailer_services.MailNotConfigured as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
            )
        except (smtplib.SMTPException, OSError):
            logger.error("send order email failed order_count=%s", len(orders))
            return Response(
                {"detail": "Không gửi được email. Kiểm tra lại cấu hình SMTP."},
                status=http_status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"sent": sent, "recipient": recipient})

    @action(detail=False, methods=["post"])
    def poll_now(self, request):
        """Trigger an immediate poll of ONE status (async, via Celery).

        Body (all optional): ``status`` (default ``processing``; must be one of
        ``services.ALLOWED_POLL_STATUSES``), ``sites`` (list of site ids; the
        whole fleet when omitted), and ``date_from``/``date_to`` (``YYYY-MM-DD``;
        when given, the sync re-pulls orders *created* in that window instead of
        using the per-site watermark). One request syncs exactly one status.
        """
        import uuid

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

        # ``platform`` scopes the run to one platform so the per-platform
        # "Đồng bộ ngay" screens never cross-pull (WooCommerce screen ≠ Sapo).
        platform = request.data.get("platform")
        if platform is not None and platform not in Site.Platform.values:
            return Response(
                {"detail": f"platform không hợp lệ: {platform}"},
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

        # ``run_id`` groups this fan-out's per-site SyncLog rows so the progress
        # banner can poll "X/Y site hoàn tất". ``expected`` must match the exact
        # set poll_all_orders will touch — ``sites_for_order_poll`` (Sapo gated +
        # deduped by store) — so ``done`` climbs to ``expected``, no more.
        run_id = str(uuid.uuid4())
        triggered_by_id = request.user.id if request.user.is_authenticated else None
        expected = len(services.sites_for_order_poll(sites or None, platform=platform))

        result = poll_all_orders.delay(
            status=status,
            site_ids=sites or None,
            date_from=date_from,
            date_to=date_to,
            run_id=run_id,
            triggered_by_id=triggered_by_id,
            platform=platform,
        )
        return Response(
            {"task_id": result.id, "status": status, "run_id": run_id, "expected": expected}
        )

    @action(detail=True, methods=["post"])
    def forward(self, request, pk=None):
        """Forward this order to the marketing department (Hub-internal, one-way).

        Idempotent and irreversible — there is no un-forward. No WooCommerce
        traffic, so no 409/502 paths; always returns the (possibly already
        forwarded) order.
        """
        order = services.forward_order(self.get_object())
        return Response(self.get_serializer(order).data)

    @action(detail=False, methods=["post"])
    def forward_bulk(self, request):
        """Forward many orders to marketing at once ("Chuyển marketing (n)").

        Body: ``{"ids": [1, 2, 3]}``. The ids are intersected with the current
        filtered queryset, so filters/permissions still apply. Capped at
        ``services.MAX_FORWARD_ORDERS``; returns how many orders flipped.
        """
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response(
                {"detail": "ids phải là danh sách id (số nguyên)."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        forwarded = services.forward_orders(self.get_queryset(), ids)
        return Response({"forwarded": forwarded})

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

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel this order on its WooCommerce site, then sync the Hub.

        Only non-terminal orders (pending/processing/on-hold) can be cancelled
        (business rule). Synchronous (a single PUT) so the UI gets the updated
        order back immediately. Errors are logged by id only (no PII).
        """
        order = self.get_object()
        try:
            order = services.mark_order_cancelled(order)
        except services.InvalidStatusTransition as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT
            )
        except httpx.HTTPError:
            logger.error(
                "cancel order failed order_id=%s site_id=%s",
                order.id,
                order.site_id,
            )
            return Response(
                {"detail": "Không thể hủy đơn trên WooCommerce."},
                status=http_status.HTTP_502_BAD_GATEWAY,
            )
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        """Mark this Sapo order paid (records a full ``sale`` transaction), then sync.

        Sapo-only (Woo orders/non-unpaid orders are rejected with 409). Synchronous
        so the UI gets the updated order back immediately. Errors are logged by id
        only (no PII).
        """
        order = self.get_object()
        try:
            order = services.mark_order_paid(order)
        except services.InvalidStatusTransition as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT
            )
        except httpx.HTTPError:
            logger.error(
                "mark_paid order failed order_id=%s site_id=%s",
                order.id,
                order.site_id,
            )
            return Response(
                {"detail": "Không thể đánh dấu đã thanh toán trên Sapo."},
                status=http_status.HTTP_502_BAD_GATEWAY,
            )
        return Response(self.get_serializer(order).data)
