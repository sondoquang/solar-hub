import django.db.models.deletion
from django.db import migrations, models


def backfill_parent(apps, schema_editor):
    """Wire the new ``parent`` self-FK from the old ``parent_name`` string.

    ``parent_name`` held the (normalized) name of the parent category; resolve
    it to the actual ``Category`` row. Names that no longer exist stay root.
    """
    Category = apps.get_model("catalog", "Category")
    by_name = {c.name: c for c in Category.objects.all()}
    to_update = []
    for cat in by_name.values():
        parent = by_name.get(cat.parent_name) if cat.parent_name else None
        if parent is not None and parent.id != cat.id:
            cat.parent_id = parent.id
            to_update.append(cat)
    if to_update:
        Category.objects.bulk_update(to_update, ["parent"])


def noop_reverse(apps, schema_editor):
    # parent_name is re-added (empty) on reverse; no data to restore.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_category_masterproduct_attributes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="catalog.category",
            ),
        ),
        migrations.RunPython(backfill_parent, noop_reverse),
        migrations.RemoveField(
            model_name="category",
            name="parent_name",
        ),
    ]
