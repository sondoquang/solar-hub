from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _sync_admin_group(sender, **kwargs):
    """Keep "Quản trị viên" holding EVERY permission after each migrate.

    New models get their permissions created by post_migrate (after the seed
    migration ran), so without this the full-access group would silently
    drift as the schema grows. Fires once per app's post_migrate — idempotent,
    and the last firing sees the complete permission set.
    """
    from django.contrib.auth.models import Group, Permission

    group = Group.objects.filter(name="Quản trị viên").first()
    if group is not None:
        group.permissions.set(Permission.objects.all())


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        post_migrate.connect(
            _sync_admin_group, dispatch_uid="accounts_sync_admin_group"
        )
