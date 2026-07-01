from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sync', '0002_synclog_run_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='synclog',
            name='triggered_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sync_logs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='synclog',
            name='started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
