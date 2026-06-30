from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_masterproduct_match_name_source_site_imported_at'),
        ('sites', '0008_site_sapo_store_host'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteMediaAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_path', models.CharField(max_length=500)),
                ('site_url', models.URLField(max_length=500)),
                ('woo_media_id', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('site', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='media_assets', to='sites.site')),
            ],
        ),
        migrations.AddConstraint(
            model_name='sitemediaasset',
            constraint=models.UniqueConstraint(fields=('site', 'source_path'), name='mediaasset_unique_site_path'),
        ),
    ]
