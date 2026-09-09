"""Delta-sync endpoints.

Cursor semantics: an opaque, monotonically increasing integer drawn from one
global sequence. It orders changes across every entity type, so one cursor is
enough and a page is always resumable -- re-requesting the same cursor returns
the same rows.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.db import sync_write_lock
from apps.core.models import SyncMutationLog

from .registry import registry
from .serializers import PushSerializer

DEFAULT_LIMIT = 200
MAX_LIMIT = 500
MAX_BATCH = 200


@api_view(["GET"])
def pull(request):
    cursor = _positive_int(request.query_params.get("cursor", 0), "cursor")
    limit = min(_positive_int(request.query_params.get("limit", DEFAULT_LIMIT), "limit"), MAX_LIMIT)
    limit = max(limit, 1)

    entities = registry.all()

    # limit + 1 per entity: if the merged result exceeds the page size we know
    # there is more, and if it does not, every entity returned everything it
    # had. Without the extra row, "exactly a full page" and "more to come" are
    # indistinguishable and the client either stops early or loops forever.
    merged = []
    for entity in entities:
        for obj in entity.model.objects.changed_since(cursor)[: limit + 1]:
            merged.append((obj.row_version, entity, obj))
    merged.sort(key=lambda item: item[0])

    has_more = len(merged) > limit
    page = merged[:limit]

    changes: dict[str, list] = {entity.name: [] for entity in entities}
    for _, entity, obj in page:
        # Tombstones are ordinary rows here. Omitting them would leave the
        # client holding a row the server no longer has.
        changes[entity.name].append(entity.serializer(obj).data)

    return Response(
        {
            "cursor": page[-1][0] if page else cursor,
            "has_more": has_more,
            "server_time": timezone.now(),
            "changes": changes,
        }
    )


@api_view(["POST"])
def push(request):
    payload = PushSerializer(data=request.data)
    payload.is_valid(raise_exception=True)

    client_id = payload.validated_data["client_id"]
    mutations = payload.validated_data["mutations"]
    if len(mutations) > MAX_BATCH:
        raise ValidationError({"mutations": f"batch of {len(mutations)} exceeds {MAX_BATCH}"})

    # Client-local ordering. A create and the update that follows it must not be
    # reordered by whatever order they arrived in the JSON array.
    mutations = sorted(mutations, key=lambda item: item["seq"])

    results = []
    with transaction.atomic(), sync_write_lock():
        for mutation in mutations:
            seen = SyncMutationLog.objects.filter(pk=mutation["mutation_id"]).first()
            if seen is not None:
                # Return the ORIGINAL response, not a bare acknowledgement: a
                # client retrying after a failure of unknown outcome needs the
                # row back to reconcile, and needs a rejection to still read as
                # a rejection.
                results.append({**seen.response_body, "duplicate": True})
                continue

            result = _apply(mutation)
            SyncMutationLog.objects.create(
                mutation_id=mutation["mutation_id"],
                client_id=client_id,
                response_body=result,
            )
            results.append(result)

    return Response(
        {
            "results": results,
            "server_time": timezone.now(),
            # Deliberately no cursor. Advancing it from the client's own writes
            # would skip anything another writer committed between this
            # client's last pull and this push. The echoed rows exist to stop
            # the UI flickering back to stale values; the cursor moves on pull.
        }
    )


def _apply(mutation: dict) -> dict:
    entity = registry.get(mutation["entity"])
    if entity is None:
        return _rejected(mutation, "UNKNOWN_ENTITY", f"no sync entity named {mutation['entity']!r}")

    try:
        # Savepoint per mutation. One poisoned mutation must not roll back the
        # other 49 in the batch, or a single bad row blocks the outbox forever.
        with transaction.atomic():
            if mutation["op"] == "delete":
                return _apply_delete(entity, mutation)
            return _apply_upsert(entity, mutation)
    except (ValidationError, DjangoValidationError) as exc:
        return _rejected(mutation, "VALIDATION_FAILED", _describe(exc))
    except IntegrityError as exc:
        return _rejected(mutation, "INTEGRITY_ERROR", str(exc))


def _apply_upsert(entity, mutation: dict) -> dict:
    instance = entity.model._base_manager.filter(pk=mutation["id"]).first()
    overwritten = _overwritten_row(entity, instance, mutation)

    serializer = entity.serializer(instance=instance, data=mutation["payload"])
    serializer.is_valid(raise_exception=True)
    # id is read-only on the wire and supplied out of band, so a client cannot
    # smuggle a different primary key inside the payload.
    obj = serializer.save(id=mutation["id"], client_ts=mutation.get("client_ts"))

    return _result(entity, mutation, obj, overwritten)


def _apply_delete(entity, mutation: dict) -> dict:
    instance = entity.model._base_manager.filter(pk=mutation["id"]).first()
    if instance is None:
        # Idempotent. Deleting a row the server never had is a no-op, not an
        # error -- the client already has it gone locally, and rejecting would
        # dead-letter a mutation that is already satisfied.
        return _result(entity, mutation, None, None)

    overwritten = _overwritten_row(entity, instance, mutation)
    if instance.deleted_at is None:
        instance.soft_delete()
    return _result(entity, mutation, instance, overwritten)


def _overwritten_row(entity, instance, mutation: dict) -> dict | None:
    """The row this mutation is about to clobber, if it moved since the client read it.

    Last-write-wins still applies -- this is not a merge queue. It exists so
    "my edit vanished" is an answerable question instead of a mystery.
    """
    base = mutation.get("base_row_version")
    if instance is None or base is None or instance.row_version <= base:
        return None
    return entity.serializer(instance).data


def _result(entity, mutation: dict, obj, overwritten: dict | None) -> dict:
    return {
        "mutation_id": str(mutation["mutation_id"]),
        "entity": entity.name,
        "status": "conflict" if overwritten else "applied",
        "row": entity.serializer(obj).data if obj is not None else None,
        "overwritten": overwritten,
    }


def _rejected(mutation: dict, reason: str, detail: str) -> dict:
    """Permanently invalid. The client must dead-letter this, never retry it."""
    return {
        "mutation_id": str(mutation["mutation_id"]),
        "entity": mutation["entity"],
        "status": "rejected",
        "reason": reason,
        "detail": detail,
        "row": None,
        "overwritten": None,
    }


def _describe(exc) -> str:
    detail = getattr(exc, "detail", None) or getattr(exc, "message_dict", None)
    return str(detail if detail is not None else exc)


def _positive_int(value, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "must be an integer"}) from exc
    if parsed < 0:
        raise ValidationError({name: "must not be negative"})
    return parsed
