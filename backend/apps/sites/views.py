"""Site API.

- ``/api/sites/`` — CRUD (ModelViewSet).
- ``POST /api/sites/{id}/test_connection/`` — verify the key via WooClient.system_status.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import services
from .models import Hosting, Site, SiteNote
from .serializers import HostingSerializer, SiteNoteSerializer, SiteSerializer


def _actor(request):
    """The authenticated user behind a request, or None (recorded as the system
    actor in the health-check history)."""
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


class SiteViewSet(viewsets.ModelViewSet):
    serializer_class = SiteSerializer
    # Server-side sort (e.g. ?ordering=name / ?ordering=-name) and search
    # (?search=...) so the frontend table works across all pages, not just the
    # current one. SearchFilter does a case-insensitive contains over name/URL.
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "base_url"]
    ordering_fields = ["name", "created_at", "status", "last_checked_at", "is_primary"]
    # Primary sites ("trang chính") float to the top so they are the first
    # thing the operator sees on the daily check.
    ordering = ["-is_primary", "-created_at"]
    action_perms = {
        "test_connection": ["sites.change_site"],
        "test_connections": ["sites.change_site"],
        "import_excel": ["sites.add_site"],
    }

    def get_queryset(self):
        qs = Site.objects.filter(is_deleted=False)
        hosting = self.request.query_params.get("hosting")
        if hosting == "none":
            qs = qs.filter(hosting__isnull=True)
        elif hosting:
            qs = qs.filter(hosting_id=hosting)
        site_status = self.request.query_params.get("status")
        if site_status in Site.Status.values:
            qs = qs.filter(status=site_status)
        platform = self.request.query_params.get("platform")
        if platform in Site.Platform.values:
            qs = qs.filter(platform=platform)
        is_primary = self.request.query_params.get("is_primary")
        if is_primary in ("true", "false"):
            qs = qs.filter(is_primary=is_primary == "true")
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
            is_primary=data.get("is_primary", False),
            platform=data.get("platform", Site.Platform.WOOCOMMERCE),
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
        result = services.test_connection(
            self.get_object(),
            check_type="manual",
            performed_by=_actor(request),
        )
        http_status = status.HTTP_200_OK if result["ok"] else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)

    @action(detail=False, methods=["post"])
    def test_connections(self, request):
        """Bulk test: body {"ids": [..]} → run each site's test sequentially."""
        ids = request.data.get("ids") or []
        sites = list(Site.objects.filter(id__in=ids, is_deleted=False))
        results = services.bulk_test_connections(
            sites, performed_by=_actor(request)
        )
        return Response({"results": results})

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
    # Server-side search (?search=...) over name / provider / account so the
    # table's search box works across all pages, not just the current one.
    filter_backends = [SearchFilter]
    search_fields = ["name", "provider", "account_username"]
    action_perms = {
        "check": ["sites.change_hosting"],
        "import_excel": ["sites.add_hosting"],
    }

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
        results = services.check_hosting(
            hosting.id, check_type="manual", performed_by=_actor(request)
        )
        return Response({"results": results})

    @action(
        detail=False,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_excel(self, request):
        """Bulk import hostings from an uploaded .xlsx (multipart field
        ``file``). Required column: name; optional: provider,
        account_username, note, check_concurrency."""
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"detail": "Thiếu file."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(services.import_hostings_from_xlsx(upload))


class SiteNoteViewSet(viewsets.ModelViewSet):
    """Per-site note history (a running journal, newest first).

    Multipart so a note carries its rich-text ``content`` plus any number of
    ``images`` file attachments in one request. List is scoped to one site via
    ``?site=<id>``; create/update/destroy go through the service layer so HTML
    is sanitized and attachments validated.
    """

    serializer_class = SiteNoteSerializer
    parser_classes = [MultiPartParser, FormParser]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = (
            SiteNote.objects.filter(is_deleted=False)
            .select_related("created_by")
            .prefetch_related("images")
        )
        site = self.request.query_params.get("site")
        if site:
            qs = qs.filter(site_id=site)
        return qs

    def _remove_image_ids(self):
        data = self.request.data
        ids = data.getlist("remove_image_ids") if hasattr(data, "getlist") else (
            data.get("remove_image_ids") or []
        )
        result = []
        for value in ids:
            try:
                result.append(int(value))
            except (TypeError, ValueError):
                continue
        return result

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.create_site_note(
            site=data["site"],
            content=data.get("content", ""),
            created_by=_actor(self.request),
            images=self.request.FILES.getlist("images"),
        )

    def perform_update(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.update_site_note(
            serializer.instance,
            content=data.get("content"),
            new_images=self.request.FILES.getlist("images"),
            remove_image_ids=self._remove_image_ids(),
        )

    def perform_destroy(self, instance):
        services.delete_site_note(instance)
