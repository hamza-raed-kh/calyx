"""Reusable migration operations for syncable tables."""

from django.db import migrations

_ATTACH = """
CREATE TRIGGER {table}_set_row_version
    BEFORE INSERT OR UPDATE ON {table}
    FOR EACH ROW EXECUTE FUNCTION sync_set_row_version();
"""

_DETACH = "DROP TRIGGER IF EXISTS {table}_set_row_version ON {table};"


def attach_row_version_trigger(table: str) -> migrations.RunSQL:
    """Give `table` a server-assigned row_version and updated_at.

    Every concrete SyncableModel needs this in its own migration -- an abstract
    base cannot carry a trigger. Forgetting it leaves row_version permanently
    NULL, so the table silently never appears in a sync pull; the
    `test_every_syncable_table_has_the_trigger` test exists to catch that.
    """
    return migrations.RunSQL(
        sql=_ATTACH.format(table=table),
        reverse_sql=_DETACH.format(table=table),
    )
