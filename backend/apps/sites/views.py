"""Site API.

- ``/api/sites/`` — CRUD (ModelViewSet).
- ``POST /api/sites/{id}/test_connection/`` — verify the key via WooClient.system_status.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import services
from .models import Hosting, Site
from .serializers import HostingSerializer, SiteSerializer


class SiteViewSet(viewsets.ModelViewSet):
    serializer_class = SiteSerializer
    # Server-side sort (e.g. ?ordering=name / ?ordering=-name) so the frontend
    # table sorter works across all pages, not just the current one.
    filter_backends = [OrderingFilter]
    ordering_fields = ["name", "created_at", "status", "last_checked_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Site.objects.filter(is_deleted=False)
        hosting = self.request.query_params.get("hosting")
        if hosting == "none":
            qs = qs.filter(hosting__isnull=True)
        elif hosting:
            qs = qs.filter(hosting_id=hosting)
        return qs

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Global up/down/unknown counts across every site, independent of the
        current page or filter — the dashboard summary needs the full picture
        even when the list itself is paginated server-side."""
        qs = Site.objects.filter(is_deleted=False)
        up = qs.filter(status=Site.Status.UP).count()
        down = qs.filter(status=Site.Status.DOWN).count()
        total = qs.count()
        return Response(
            {"total": total, "up": up, "down": down, "unknown": total - up - down}
        )

    def perform_create(self, serializer):
        data = serializer.validated_data
        site = services.create_site(
            name=data["name"],
            base_url=data["base_url"],
            consumer_key=data["consumer_key"],
            consumer_secret=data["consumer_secret"],
            hosting=data.get("hosting"),
        )
        serializer.instance = site

    def perform_update(self, serializer):
        data = serializer.validated_data
        consumer_secret = data.pop("consumer_secret", None)
        serializer.instance = services.update_site(
            serializer.instance, consumer_secret=consumer_secret, **data
        )

    def perform_destroy(self, instance):
        services.delete_site(instance)

    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None):
        result = services.test_connection(self.get_object())
        http_status = status.HTTP_200_OK if result["ok"] else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)

    @action(detail=False, methods=["post"])
    def test_connections(self, request):
        """Bulk test: body {"ids": [..]} → run each site's test sequentially."""
        ids = request.data.get("ids") or []
        sites = list(Site.objects.filter(id__in=ids, is_deleted=False))
        return Response({"results": services.bulk_test_connections(sites)})

    @action(
        detail=False,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_excel(self, request):
        """Bulk import from an uploaded .xlsx (multipart field ``file``). An
        optional ``hosting`` field assigns every imported site to that hosting."""
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"detail": "Thiếu file."}, status=status.HTTP_400_BAD_REQUEST
            )
        hosting = None
        hosting_id = request.data.get("hosting") or None
        if hosting_id:
            hosting = Hosting.objects.filter(id=hosting_id, is_deleted=False).first()
            if hosting is None:
                return Response(
                    {"detail": "Hosting không hợp lệ."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(services.import_sites_from_xlsx(upload, hosting=hosting))


class HostingViewSet(viewsets.ModelViewSet):
    """CRUD for hostings (site groups) + an on-demand grouped health-check."""

    serializer_class = HostingSerializer

    def get_queryset(self):
        return (
            Hosting.objects.filter(is_deleted=False)
            .prefetch_related("sites")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        serializer.instance = services.create_hosting(**serializer.validated_data)

    def perform_update(self, serializer):
        serializer.instance = services.update_hosting(
            serializer.instance, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        services.delete_hosting(instance)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """Health-check every site of this hosting now, throttled to its
        check_concurrency. Returns per-site results."""
        hosting = self.get_object()
        return Response({"results": services.check_hosting(hosting.id)})
