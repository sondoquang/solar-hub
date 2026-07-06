"""Seed the default RBAC groups and grandfather existing users.

Runs once at deploy: creates "Quản trị viên" (full access), "Nhân viên" and
"Marketing", then puts EVERY existing user into the full-access group so
nobody is locked out when ``RBACPermission`` starts enforcing. Admins re-group
people afterwards via the matrix UI.

``seed`` is idempotent (``get_or_create`` + ``set``) so tests can call it
directly.
"""

from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations

# Nhân viên: full view + create/edit on business resources, order operations
# and the sync/push custom perms. No deletes, no auth.*, no mail changes.
STAFF_CODENAMES = [
    # view
    "view_order", "view_masterproduct", "view_category",
    "view_site", "view_hosting", "view_sitenote",
    "view_domaininfo", "view_healthcheck", "view_synclog", "view_mailsettings",
    # create/edit
    "add_masterproduct", "change_masterproduct",
    "add_category", "change_category",
    "add_site", "change_site",
    "add_hosting", "change_hosting",
    "add_sitenote", "change_sitenote",
    # order operations
    "change_order", "sync_order", "forward_order", "email_order",
    # business actions
    "push_masterproduct", "pull_category", "refresh_domaininfo",
]

# Marketing: read-only over the business data it needs.
MARKETING_CODENAMES = [
    "view_order", "view_masterproduct", "view_category",
    "view_site", "view_domaininfo", "view_healthcheck", "view_synclog",
]


def seed(apps, schema_editor):
    # Permissions are normally created by the post_migrate signal — i.e. AFTER
    # this data migration on a fresh ``migrate``. Force-create them first so
    # the groups below can reference them (incl. the custom Meta.permissions).
    for app_config in django_apps.get_app_configs():
        create_permissions(app_config, apps=apps, verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")

    admin, _ = Group.objects.get_or_create(name="Quản trị viên")
    admin.permissions.set(Permission.objects.all())

    staff, _ = Group.objects.get_or_create(name="Nhân viên")
    staff.permissions.set(Permission.objects.filter(codename__in=STAFF_CODENAMES))

    marketing, _ = Group.objects.get_or_create(name="Marketing")
    marketing.permissions.set(
        Permission.objects.filter(codename__in=MARKETING_CODENAMES)
    )

    # Grandfather every existing account into full access so the enforcement
    # flip changes nothing until an admin re-groups them.
    existing = list(User.objects.all())
    if existing:
        admin.user_set.add(*existing)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("catalog", "0009_alter_category_options_alter_masterproduct_options"),
        ("orders", "0006_alter_order_options"),
        ("domains", "0002_alter_domaininfo_options"),
        ("mailer", "0003_alter_mailsettings_options"),
        # The remaining business apps must be in the migration state too, or
        # create_permissions() skips them on a fresh DB and the codename
        # filters above silently miss their perms (sites/sync/monitoring
        # otherwise order AFTER accounts in the plan).
        ("sites", "0008_site_sapo_store_host"),
        ("sync", "0005_notification"),
        ("monitoring", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
