"""Site API.

- ``/api/sites/`` — CRUD (ModelViewSet).
- ``POST /api/sites/{id}/test_connection/`` — verify the key via WooClient.system_status.

NOTE: permissions are AllowAny for now (login not built yet); tighten in a later phase.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import services
from .models import Site
from .serializers import SiteSerializer


class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all().order_by("-created_at")
    serializer_class = SiteSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        data = serializer.validated_data
        site = services.create_site(
            name=data["name"],
            base_url=data["base_url"],
            consumer_key=data["consumer_key"],
            consumer_secret=data["consumer_secret"],
        )
        serializer.instance = site

    def perform_update(self, serializer):
        data = serializer.validated_data
        consumer_secret = data.pop("consumer_secret", None)
        serializer.instance = services.update_site(
            serializer.instance, consumer_secret=consumer_secret, **data
        )

    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None):
        result = services.test_connection(self.get_object())
        http_status = status.HTTP_200_OK if result["ok"] else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)

    @action(detail=False, methods=["post"])
    def test_connections(self, request):
        """Bulk test: body {"ids": [..]} → run each site's test sequentially."""
        ids = request.data.get("ids") or []
        sites = list(Site.objects.filter(id__in=ids))
        return Response({"results": services.bulk_test_connections(sites)})

    @action(
        detail=False,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_excel(self, request):
        """Bulk import from an uploaded .xlsx (multipart field ``file``)."""
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"detail": "Thiếu file."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(services.import_sites_from_xlsx(upload))
