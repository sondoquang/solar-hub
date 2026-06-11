from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0005_site_site_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='is_primary',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
