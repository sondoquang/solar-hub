"""Backfill: existing completed orders count as forwarded to marketing.

A completed order is treated as "đã chuyển sang bộ phận marketing" (see
``apps.orders.services._auto_forward_if_completed``). That rule only fires on
upsert going forward, so this one-off migration applies it to orders already
stored as completed. One-way by design — ``reverse`` is a no-op.
"""

from django.db import migrations
from django.db.models import F


def forward(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    qs = Order.objects.filter(status="completed", forwarded=False)
    # Use the order's last-modified-on-site time as the forward timestamp where
    # available; fall back to creation time for rows missing date_modified_woo.
    qs.filter(date_modified_woo__isnull=False).update(
        forwarded=True, forwarded_at=F("date_modified_woo")
    )
    qs.filter(date_modified_woo__isnull=True).update(
        forwarded=True, forwarded_at=F("date_created_woo")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_order_date_modified_woo_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
