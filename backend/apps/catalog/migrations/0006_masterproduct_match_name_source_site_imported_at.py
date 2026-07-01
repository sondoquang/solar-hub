from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0005_categorymapping_woo_name'),
        ('sites', '0008_site_sapo_store_host'),
    ]

    operations = [
        migrations.AddField(
            model_name='masterproduct',
            name='match_name',
            field=models.CharField(blank=True, db_index=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='masterproduct',
            name='source_site',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='imported_products', to='sites.site'),
        ),
        migrations.AddField(
            model_name='masterproduct',
            name='imported_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
