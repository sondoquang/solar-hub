from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0004_sitenote_sitenoteimage_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='site_type',
            field=models.CharField(
                choices=[
                    ('website', 'Website'),
                    ('api', 'API'),
                    ('mail', 'Mail Server'),
                    ('database', 'Database'),
                ],
                default='website',
                max_length=20,
            ),
        ),
    ]
