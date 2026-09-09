import uuid

import pytest
from django.urls import reverse

from apps.core.models import SyncMutationLog
from apps.core.uuids import uuid7
from apps.synctest.models import Widget

pytestmark = pytest.mark.django_db


def mutation(**overrides):
    base = {
        "mutation_id": str(uuid7()),
        "seq": 1,
        "entity": "widgets",
        "op": "upsert",
        "id": str(uuid7()),
        "client_ts": "2026-09-09T10:00:00Z",
        "payload": {"name": "thing"},
    }
    return {**base, **overrides}


def push(api, *mutations, client_id="device-1"):
    return api.post(
        reverse("sync:push"),
        {"client_id": client_id, "mutations": list(mutations)},
        format="json",
    )


def test_requires_authentication(anon):
    assert anon.post(reverse("sync:push"), {}, format="json").status_code in (401, 403)


def test_create_applies_and_echoes_the_canonical_row(api):
    item = mutation()
    body = push(api, item).json()
    result = body["results"][0]

    assert result["status"] == "applied"
    assert result["row"]["id"] == item["id"]
    assert result["row"]["name"] == "thing"
    # The echoed row must carry the server-assigned version: the client writes
    # it verbatim, and a missing version would make it re-push forever.
    assert result["row"]["row_version"] is not None
    assert Widget.objects.get(pk=item["id"]).name == "thing"


def test_update_applies(api):
    widget = Widget.objects.create(name="before")
    push(api, mutation(id=str(widget.pk), payload={"name": "after"}))
    widget.refresh_from_db()
    assert widget.name == "after"


def test_delete_soft_deletes(api):
    widget = Widget.objects.create(name="doomed")
    result = push(api, mutation(id=str(widget.pk), op="delete", payload={})).json()["results"][0]

    widget.refresh_from_db()
    assert result["status"] == "applied"
    assert widget.deleted_at is not None
    assert result["row"]["deleted_at"] is not None


def test_deleting_something_the_server_never_had_is_a_no_op(api):
    """Rejecting would dead-letter a mutation that is already satisfied."""
    result = push(api, mutation(op="delete", payload={})).json()["results"][0]
    assert result["status"] == "applied"
    assert result["row"] is None


def test_client_ts_is_recorded_but_never_authoritative(api):
    item = mutation(client_ts="1999-01-01T00:00:00Z")
    push(api, item)
    widget = Widget.objects.get(pk=item["id"])
    assert widget.client_ts.year == 1999
    # Server clock wins for ordering; a device with a wrong clock cannot shadow
    # server state.
    assert widget.updated_at.year >= 2020


def test_mutations_apply_in_seq_order_not_array_order(api):
    """A create and the update that follows it must not be reordered."""
    entity_id = str(uuid7())
    body = push(
        api,
        mutation(seq=2, id=entity_id, payload={"name": "second"}),
        mutation(seq=1, id=entity_id, payload={"name": "first"}),
    ).json()

    assert [r["status"] for r in body["results"]] == ["applied", "applied"]
    assert Widget.objects.get(pk=entity_id).name == "second"


# --- idempotency -------------------------------------------------------------


def test_replaying_a_mutation_creates_no_second_row(api):
    item = mutation()
    push(api, item)
    body = push(api, item).json()

    assert body["results"][0]["duplicate"] is True
    assert body["results"][0]["status"] == "applied"
    assert Widget.objects.count() == 1


def test_a_replay_returns_the_original_response_not_a_bare_ack(api):
    """A client retrying after an unknown outcome needs the row back to reconcile."""
    item = mutation()
    first = push(api, item).json()["results"][0]
    replay = push(api, item).json()["results"][0]

    assert replay["row"] == first["row"]


def test_a_replayed_rejection_is_still_a_rejection(api):
    item = mutation(entity="nope")
    push(api, item)
    replay = push(api, item).json()["results"][0]

    assert replay["status"] == "rejected"
    assert replay["duplicate"] is True


def test_every_applied_mutation_is_logged(api):
    push(api, mutation(seq=1), mutation(seq=2))
    assert SyncMutationLog.objects.count() == 2


# --- poison isolation --------------------------------------------------------


def test_one_invalid_mutation_does_not_block_the_batch(api):
    """A poison mutation retrying forever is the likeliest way this breaks."""
    good = [mutation(seq=index, payload={"name": f"n{index}"}) for index in range(49)]
    poison = mutation(seq=49, payload={"name": "x" * 500})  # exceeds max_length=50

    body = push(api, *good, poison).json()
    statuses = [r["status"] for r in body["results"]]

    assert statuses.count("applied") == 49
    assert statuses.count("rejected") == 1
    assert Widget.objects.count() == 49


def test_rejection_names_a_reason_the_client_can_act_on(api):
    result = push(api, mutation(payload={"name": "x" * 500})).json()["results"][0]
    assert result["status"] == "rejected"
    assert result["reason"] == "VALIDATION_FAILED"
    assert "name" in result["detail"]


def test_unknown_entity_is_rejected_not_a_server_error(api):
    result = push(api, mutation(entity="widgetz")).json()["results"][0]
    assert result["status"] == "rejected"
    assert result["reason"] == "UNKNOWN_ENTITY"


def test_batch_size_is_capped(api):
    body = push(api, *[mutation(seq=i) for i in range(201)])
    assert body.status_code == 400


# --- conflicts ---------------------------------------------------------------


def test_stale_write_still_applies_but_reports_what_it_overwrote(api):
    """Last-write-wins is the rule; the conflict record just makes it visible."""
    widget = Widget.objects.create(name="original")
    stale_base = widget.row_version

    widget.name = "changed by someone else"
    widget.save()

    result = push(
        api,
        mutation(id=str(widget.pk), base_row_version=stale_base, payload={"name": "mine"}),
    ).json()["results"][0]

    widget.refresh_from_db()
    assert result["status"] == "conflict"
    assert result["overwritten"]["name"] == "changed by someone else"
    assert widget.name == "mine"


def test_a_fresh_write_is_not_flagged_as_a_conflict(api):
    widget = Widget.objects.create(name="original")
    result = push(
        api,
        mutation(id=str(widget.pk), base_row_version=widget.row_version, payload={"name": "mine"}),
    ).json()["results"][0]

    assert result["status"] == "applied"
    assert result["overwritten"] is None


# --- the client cannot forge server-owned fields -----------------------------


def test_payload_cannot_smuggle_a_different_primary_key(api):
    item = mutation(payload={"name": "n", "id": str(uuid.uuid4())})
    result = push(api, item).json()["results"][0]
    assert result["row"]["id"] == item["id"]


def test_payload_cannot_set_row_version(api):
    item = mutation(payload={"name": "n", "row_version": 999_999})
    result = push(api, item).json()["results"][0]
    assert result["row"]["row_version"] != 999_999


def test_push_returns_no_cursor(api):
    """Advancing the cursor from a client's own writes would skip anything another
    writer committed since that client last pulled. The cursor moves on pull."""
    body = push(api, mutation()).json()
    assert "cursor" not in body


def test_pushed_rows_come_back_on_the_next_pull(api):
    item = mutation()
    push(api, item)

    rows = api.get(reverse("sync:pull"), {"cursor": 0}).json()["changes"]["widgets"]
    assert [row["id"] for row in rows] == [item["id"]]


def test_the_same_mutation_twice_in_one_batch_applies_once(api):
    """A client bug or an over-eager retry can duplicate within a single batch.
    The log is read inside the transaction, so the second copy sees the first."""
    item = mutation()
    body = push(api, item, {**item, "seq": 2}).json()

    statuses = [r["status"] for r in body["results"]]
    assert statuses == ["applied", "applied"]
    assert body["results"][1]["duplicate"] is True
    assert Widget.objects.count() == 1
    assert SyncMutationLog.objects.count() == 1
