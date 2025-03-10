# Generated by Plain 0.31.0 on 2025-03-08 21:33

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plaincache", "0002_rename_cacheitem_cacheditem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cacheditem",
            name="key",
            field=models.CharField(max_length=255),
        ),
        migrations.AddConstraint(
            model_name="cacheditem",
            constraint=models.UniqueConstraint(
                fields=("key",), name="plaincache_cacheditem_unique_key"
            ),
        ),
    ]
