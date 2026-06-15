"""Output shapes of the category-run report (plain Serializers — a "run" is a
roll-up over SyncLog rows, not a model; the dicts come from services.py)."""

from rest_framework import serializers


class RunCategorySerializer(serializers.Serializer):
    """One Woo category of one site and the Hub Category it converged to."""

    woo_id = serializers.IntegerField()
    woo_name = serializers.CharField(allow_blank=True)
    hub_id = serializers.IntegerField()
    hub_name = serializers.CharField()


class RunSiteSerializer(serializers.Serializer):
    """One site's outcome within a run (null site_id = site deleted since;
    the name/url/hosting then come from the snapshot taken at pull time)."""

    site_id = serializers.IntegerField(allow_null=True)
    site_name = serializers.CharField(allow_blank=True)
    site_url = serializers.CharField(allow_blank=True)
    hosting = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    error = serializers.CharField(allow_blank=True)
    pulled = serializers.IntegerField()
    mapped = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    categories = RunCategorySerializer(many=True)


class CategoryRunListSerializer(serializers.Serializer):
    """One row of the runs table.

    ``duration_seconds`` is the run's wall-clock span, ``triggered_by`` the
    clicking admin (null for periodic/legacy runs), ``site_label`` the single
    site's name for one-site runs (null otherwise → the UI shows "N site")."""

    run_id = serializers.CharField()
    started_at = serializers.DateTimeField()
    site_count = serializers.IntegerField()
    total_pulled = serializers.IntegerField()
    total_mapped = serializers.IntegerField()
    error_count = serializers.IntegerField()
    status = serializers.CharField()
    duration_seconds = serializers.IntegerField()
    triggered_by = serializers.CharField(allow_null=True)
    site_label = serializers.CharField(allow_null=True, allow_blank=True)


class CategoryRunDetailSerializer(CategoryRunListSerializer):
    """Run summary + its per-site rows (detail modal / export source)."""

    sites = RunSiteSerializer(many=True)
