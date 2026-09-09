"""Sync primitives shared by every syncable table."""

from datetime import timedelta

from django.db import models
from django.utils import timezone

from .uuids import uuid7


class SyncableQuerySet(models.QuerySet):
    def live(self):
        """Rows that are not tombstoned. Sync pulls must NOT use this."""
        return self.filter(deleted_at__isnull=True)

    def changed_since(self, cursor: int):
        """Everything a client at `cursor` has not seen, tombstones included."""
        return self.filter(row_version__gt=cursor).order_by("row_version")


class SyncableModel(models.Model):
    """Base for anything the client mirrors locally.

    Concrete subclasses MUST call `attach_row_version_trigger(<table>)` in their
    migration; a trigger cannot live on an abstract base.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    # Assigned by the sync_set_row_version trigger from one global sequence
    # shared across every table, so a single cursor orders all entity types.
    # Nullable only so the INSERT can omit it; the trigger always fills it.
    row_version = models.BigIntegerField(editable=False, null=True, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)

    # Server clock, set by the trigger. Display and audit only -- conflict
    # resolution uses row_version, never a timestamp.
    updated_at = models.DateTimeField(editable=False, null=True)

    # What the device claimed the time was. Recorded for debugging and for
    # validating the backfill window; NEVER consulted to resolve a conflict, so
    # a device with a wrong clock cannot shadow server state.
    client_ts = models.DateTimeField(null=True, blank=True, editable=False)

    # Soft delete. Tombstones are ordinary rows in a sync pull -- omitting them
    # would leave the client holding a row the server no longer has.
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SyncableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # The trigger assigns row_version and updated_at, so the in-memory
        # instance is stale the moment it is written. Refresh them: the sync
        # push handler echoes this row back to the client, which advances its
        # cursor from it, and a stale value there would make the client re-pull
        # its own write forever.
        fresh = (
            type(self)._base_manager.filter(pk=self.pk).values("row_version", "updated_at").first()
        )
        if fresh is not None:
            self.row_version = fresh["row_version"]
            self.updated_at = fresh["updated_at"]

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, *, when=None):
        self.deleted_at = when or timezone.now()
        self.save(update_fields=["deleted_at"])


class SyncMutationLog(models.Model):
    """Idempotency ledger for pushed mutations.

    Stores the *response*, not just a marker. A client that retries after a
    network failure of unknown outcome needs the original result back -- being
    told only "already applied" leaves it unable to reconcile.
    """

    mutation_id = models.UUIDField(primary_key=True)
    client_id = models.CharField(max_length=64)
    applied_at = models.DateTimeField(default=timezone.now, db_index=True)
    response_body = models.JSONField()

    class Meta:
        verbose_name = "sync mutation log entry"
        verbose_name_plural = "sync mutation log"

    def __str__(self) -> str:
        return f"{self.mutation_id} from {self.client_id}"

    @classmethod
    def prune(cls, *, older_than_days: int = 90) -> int:
        cutoff = timezone.now() - timedelta(days=older_than_days)
        deleted, _ = cls.objects.filter(applied_at__lt=cutoff).delete()
        return deleted
