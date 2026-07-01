from django.db import migrations, models

import apps.mailer.models


class Migration(migrations.Migration):

    dependencies = [
        ("mailer", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mailsettings",
            name="digest_times",
            field=models.JSONField(
                blank=True, default=apps.mailer.models.default_digest_times
            ),
        ),
    ]
