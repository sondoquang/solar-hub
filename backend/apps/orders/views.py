"""Orders API — read-only aggregated orders + a manual poll trigger.

- ``GET  /api/orders/``           — paginated list (search / filters / sort).
- ``GET  /api/orders/{id}/``      — one order (detail modal).
- ``GET  /api/orders/stats/``     — totals/revenue for the current filter.
- ``POST /api/orders/poll_now/``  — kick the poll fan-out (the "Đồng bộ ngay" button).

Orders are pulled in by the periodic poll (apps/sync/tasks); the Hub does not
create/update them by hand, so there is no write endpoint beyond the trigger.
"""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from . import services
from .models import Order
from .serializers import OrderSerializer


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
        """Trigger an immediate poll across all sites (async, via Celery)."""
        from apps.sync.tasks import poll_all_orders

        result = poll_all_orders.delay()
        return Response({"task_id": result.id})
