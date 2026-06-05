import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0002_site_soft_delete"),
    ]

    operations = [
        migrations.CreateModel(
            name="Hosting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("provider", models.CharField(blank=True, max_length=120)),
                ("account_username", models.CharField(blank=True, max_length=120)),
                ("note", models.TextField(blank=True)),
                ("check_concurrency", models.PositiveSmallIntegerField(default=5)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name="site",
            name="hosting",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sites",
                to="sites.hosting",
            ),
        ),
    ]
