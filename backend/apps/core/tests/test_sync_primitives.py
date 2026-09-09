import time
import uuid
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.core.db import sync_write_lock
from apps.core.models import SyncableModel, SyncMutationLog
from apps.core.uuids import uuid7
from apps.synctest.models import Gadget, Widget

pytestmark = pytest.mark.django_db


# --- UUIDv7 ------------------------------------------------------------------


def test_uuid7_has_correct_version_and_variant():
    value = uuid7()
    assert value.version == 7
    assert (value.int >> 62) & 0b11 == 0b10  # RFC 9562 variant


def test_uuid7_is_time_ordered():
    values = [uuid7() for _ in range(200)]
    assert values == sorted(values), "v7 must sort by creation time"


def test_uuid7_is_monotonic_within_one_millisecond():
    """A tight burst -- draining an offline outbox -- must still be ordered.

    Pure random rand_a would fail this roughly half the time per adjacent pair.
    """
    start = time.time_ns() // 1_000_000
    values = [uuid7() for _ in range(500)]
    assert time.time_ns() // 1_000_000 - start <= 5, "burst was too slow to test the same-ms path"
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_uuid7_embeds_current_timestamp():
    before = int(timezone.now().timestamp() * 1000)
    value = uuid7()
    after = int(timezone.now().timestamp() * 1000)
    embedded = value.int >> 80
    assert before - 1000 <= embedded <= after + 1000


# --- row_version -------------------------------------------------------------


def test_insert_assigns_row_version():
    widget = Widget.objects.create(name="a")
    assert widget.row_version is not None
    assert widget.updated_at is not None


def test_update_bumps_row_version():
    widget = Widget.objects.create(name="a")
    first = widget.row_version

    widget.name = "b"
    widget.save()

    assert widget.row_version > first


def test_row_version_is_globally_ordered_across_tables():
    """The whole point of one shared sequence: a single cursor orders everything."""
    widget = Widget.objects.create(name="w1")
    gadget = Gadget.objects.create(name="g1")
    widget2 = Widget.objects.create(name="w2")

    versions = [widget.row_version, gadget.row_version, widget2.row_version]
    assert versions == sorted(versions)
    assert len(set(versions)) == 3, "a row_version must never be reused"


def test_save_refreshes_in_memory_row_version():
    """The push handler echoes this instance back; a stale value here would make
    the client re-pull its own write forever."""
    widget = Widget.objects.create(name="a")
    from_db = Widget.objects.get(pk=widget.pk)
    assert widget.row_version == from_db.row_version
    assert widget.updated_at == from_db.updated_at


def test_raw_sql_update_still_gets_a_row_version():
    """updated_at is the trigger's job, not Django's, so nothing can bypass it."""
    widget = Widget.objects.create(name="a")
    before = widget.row_version

    with connection.cursor() as cursor:
        cursor.execute("UPDATE synctest_widget SET name = 'raw' WHERE id = %s", [str(widget.pk)])

    widget.refresh_from_db()
    assert widget.row_version > before
    assert widget.name == "raw"


def test_queryset_update_bumps_row_version():
    widget = Widget.objects.create(name="a")
    before = widget.row_version

    Widget.objects.filter(pk=widget.pk).update(name="bulk")

    widget.refresh_from_db()
    assert widget.row_version > before


# --- tombstones and cursors --------------------------------------------------


def test_soft_delete_sets_tombstone_and_bumps_version():
    widget = Widget.objects.create(name="a")
    before = widget.row_version

    widget.soft_delete()

    assert widget.is_deleted
    assert widget.deleted_at is not None
    assert widget.row_version > before


def test_changed_since_includes_tombstones():
    """A pull that hides deletes leaves the client holding rows the server lost."""
    widget = Widget.objects.create(name="a")
    cursor = widget.row_version
    widget.soft_delete()

    changed = list(Widget.objects.changed_since(cursor))

    assert [w.pk for w in changed] == [widget.pk]
    assert changed[0].is_deleted


def test_changed_since_excludes_already_seen_rows():
    widget = Widget.objects.create(name="a")
    assert list(Widget.objects.changed_since(widget.row_version)) == []


def test_live_excludes_tombstones_but_changed_since_does_not():
    kept = Widget.objects.create(name="kept")
    gone = Widget.objects.create(name="gone")
    gone.soft_delete()

    assert list(Widget.objects.live()) == [kept]
    assert {w.pk for w in Widget.objects.changed_since(0)} == {kept.pk, gone.pk}


# --- trigger coverage --------------------------------------------------------


def test_every_syncable_table_has_the_trigger():
    """Forgetting attach_row_version_trigger() in a migration leaves row_version
    NULL forever, so the table silently never appears in a sync pull. Catch it
    here rather than in production."""
    from django.apps import apps as django_apps

    syncable = [
        model
        for model in django_apps.get_models()
        if issubclass(model, SyncableModel) and not model._meta.abstract
    ]
    assert syncable, "no syncable models found -- this test would pass vacuously"

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND t.tgname LIKE '%%_set_row_version'"
        )
        triggered = {row[0] for row in cursor.fetchall()}

    missing = {m._meta.db_table for m in syncable} - triggered
    assert not missing, f"syncable tables without a row_version trigger: {sorted(missing)}"


# --- advisory lock -----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_sync_write_lock_requires_a_transaction():
    """A transaction-scoped lock taken outside a transaction is released
    immediately, which would silently provide no serialisation at all.

    Needs transaction=True: the default django_db fixture wraps each test in an
    atomic block, so in_atomic_block would never be False.
    """
    assert not connection.in_atomic_block
    with pytest.raises(RuntimeError, match="must be used inside a transaction"), sync_write_lock():
        pass


def test_sync_write_lock_is_held_inside_a_transaction():
    held = "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
    with transaction.atomic(), sync_write_lock(), connection.cursor() as cursor:
        cursor.execute(held)
        assert cursor.fetchone()[0] == 1


# --- mutation log ------------------------------------------------------------


def test_mutation_log_stores_the_response_not_just_a_marker():
    """A client retrying after an unknown outcome needs the original result
    back, not merely 'already applied'."""
    mutation_id = uuid.uuid4()
    SyncMutationLog.objects.create(
        mutation_id=mutation_id,
        client_id="device-1",
        response_body={"status": "applied", "row": {"id": "abc"}},
    )

    stored = SyncMutationLog.objects.get(pk=mutation_id)
    assert stored.response_body["row"]["id"] == "abc"


def test_mutation_log_prune_drops_only_old_entries():
    old = SyncMutationLog.objects.create(mutation_id=uuid.uuid4(), client_id="d", response_body={})
    SyncMutationLog.objects.filter(pk=old.pk).update(
        applied_at=timezone.now() - timedelta(days=120)
    )
    recent = SyncMutationLog.objects.create(
        mutation_id=uuid.uuid4(), client_id="d", response_body={}
    )

    assert SyncMutationLog.prune() == 1
    assert list(SyncMutationLog.objects.values_list("pk", flat=True)) == [recent.pk]
