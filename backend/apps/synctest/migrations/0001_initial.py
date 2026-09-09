import django.utils.timezone
from django.db import migrations, models

import apps.core.uuids
from apps.core.migration_ops import attach_row_version_trigger


def syncable_fields():
    return [
        ("id", models.UUIDField(default=apps.core.uuids.uuid7, editable=False, primary_key=True, serialize=False)),
        ("row_version", models.BigIntegerField(db_index=True, editable=False, null=True)),
        ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
        ("updated_at", models.DateTimeField(editable=False, null=True)),
        ("client_ts", models.DateTimeField(blank=True, editable=False, null=True)),
        ("deleted_at", models.DateTimeField(blank=True, null=True)),
        ("name", models.CharField(max_length=50)),
    ]


class Migration(migrations.Migration):
    initial = True

    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.CreateModel(name="Widget", fields=syncable_fields(), options={"abstract": False}),
        migrations.CreateModel(name="Gadget", fields=syncable_fields(), options={"abstract": False}),
        attach_row_version_trigger("synctest_widget"),
        attach_row_version_trigger("synctest_gadget"),
    ]
