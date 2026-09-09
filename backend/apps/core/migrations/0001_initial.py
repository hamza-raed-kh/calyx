from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models
from django.utils import timezone

# One sequence shared by every syncable table, so a single integer cursor
# totally orders changes across all entity types. A per-table sequence would
# force the client to track one cursor per entity and would make a globally
# ordered, resumable page impossible.
CREATE_SEQUENCE = "CREATE SEQUENCE IF NOT EXISTS sync_seq AS bigint START WITH 1;"
DROP_SEQUENCE = "DROP SEQUENCE IF EXISTS sync_seq;"

# updated_at is set here rather than by Django's auto_now so that raw SQL and
# admin edits cannot bypass it. The trigger is the single writer of both fields.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION sync_set_row_version() RETURNS trigger AS $$
BEGIN
    NEW.row_version := nextval('sync_seq');
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
DROP_FUNCTION = "DROP FUNCTION IF EXISTS sync_set_row_version();"


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        # Needed by the habit engine's schedule-version exclusion constraints,
        # which combine an equality column with a range overlap.
        BtreeGistExtension(),
        migrations.RunSQL(sql=CREATE_SEQUENCE, reverse_sql=DROP_SEQUENCE),
        migrations.RunSQL(sql=CREATE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.CreateModel(
            name="SyncMutationLog",
            fields=[
                ("mutation_id", models.UUIDField(primary_key=True, serialize=False)),
                ("client_id", models.CharField(max_length=64)),
                ("applied_at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("response_body", models.JSONField()),
            ],
            options={
                "verbose_name": "sync mutation log entry",
                "verbose_name_plural": "sync mutation log",
            },
        ),
    ]
