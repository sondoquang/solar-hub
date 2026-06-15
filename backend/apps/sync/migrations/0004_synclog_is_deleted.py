from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sync', '0003_synclog_triggered_by_started_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='synclog',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
    ]
