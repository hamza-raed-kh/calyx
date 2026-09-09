"""Database-level sync primitives."""

from contextlib import contextmanager

from django.db import connection

# Arbitrary but fixed. Every mutating request takes this one lock, which makes
# writes totally ordered -- see sync_write_lock() for why that matters.
SYNC_WRITE_LOCK_KEY = 4_919_284_710


@contextmanager
def sync_write_lock():
    """Serialise all mutating writes for the duration of the transaction.

    Without this, `row_version` values can interleave across concurrent commits:
    the sequence is drawn at statement time but the row only becomes *visible* at
    commit time, so a transaction that draws version 100 and commits after a
    client has already pulled past 101 produces a row that client can never see.
    Silent and permanent -- the classic way sequence/timestamp sync breaks.

    Taking one advisory lock per write makes that interleaving impossible.
    Write throughput is irrelevant here: single user, one device at a time.

    The lock is transaction-scoped, so it is released on commit or rollback with
    nothing to unwind.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(
            "sync_write_lock() must be used inside a transaction; "
            "a transaction-scoped advisory lock taken outside one is released immediately"
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [SYNC_WRITE_LOCK_KEY])
    yield
