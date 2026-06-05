from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="is_deleted",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="site",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
