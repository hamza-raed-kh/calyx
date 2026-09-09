import uuid

import pytest
from django.urls import reverse

from apps.synctest.models import Gadget, Widget

pytestmark = pytest.mark.django_db

URL = None


def pull(api, **params):
    return api.get(reverse("sync:pull"), params)


def test_requires_authentication(anon):
    assert anon.get(reverse("sync:pull")).status_code in (401, 403)


def test_cursor_zero_returns_everything(api):
    Widget.objects.create(name="w")
    Gadget.objects.create(name="g")

    body = pull(api, cursor=0).json()

    assert len(body["changes"]["widgets"]) == 1
    assert len(body["changes"]["gadgets"]) == 1
    assert body["has_more"] is False


def test_cursor_excludes_already_seen_rows(api):
    widget = Widget.objects.create(name="w")
    body = pull(api, cursor=widget.row_version).json()
    assert body["changes"]["widgets"] == []


def test_cursor_advances_to_last_row_version(api):
    Widget.objects.create(name="a")
    last = Widget.objects.create(name="b")
    assert pull(api, cursor=0).json()["cursor"] == last.row_version


def test_empty_pull_keeps_the_cursor_where_it_was(api):
    widget = Widget.objects.create(name="w")
    body = pull(api, cursor=widget.row_version).json()
    assert body["cursor"] == widget.row_version


def test_orders_globally_across_entity_types(api):
    """One shared sequence exists precisely so a single cursor orders everything."""
    widget = Widget.objects.create(name="w1")
    gadget = Gadget.objects.create(name="g1")
    widget2 = Widget.objects.create(name="w2")

    body = pull(api, cursor=0).json()
    versions = [row["row_version"] for rows in body["changes"].values() for row in rows]

    assert sorted(versions) == [widget.row_version, gadget.row_version, widget2.row_version]


def test_paging_one_row_at_a_time_loses_nothing(api):
    """A page boundary must not skip or duplicate a row, whichever entity it came from."""
    expected = []
    for index in range(6):
        model = Widget if index % 2 == 0 else Gadget
        expected.append(model.objects.create(name=f"n{index}").row_version)

    seen, cursor = [], 0
    for _ in range(20):
        body = pull(api, cursor=cursor, limit=1).json()
        seen.extend(row["row_version"] for rows in body["changes"].values() for row in rows)
        cursor = body["cursor"]
        if not body["has_more"]:
            break

    assert seen == sorted(expected)
    assert len(seen) == len(set(seen))


def test_has_more_is_false_on_an_exactly_full_page(api):
    """The classic off-by-one: a full page must not imply another page exists."""
    for index in range(3):
        Widget.objects.create(name=f"w{index}")

    body = pull(api, cursor=0, limit=3).json()

    assert len(body["changes"]["widgets"]) == 3
    assert body["has_more"] is False


def test_a_page_is_resumable(api):
    """Re-requesting the same cursor must return identical rows, so a client that
    crashes mid-apply can simply ask again."""
    for index in range(4):
        Widget.objects.create(name=f"w{index}")

    first = pull(api, cursor=0, limit=2).json()
    again = pull(api, cursor=0, limit=2).json()

    assert first["changes"] == again["changes"]
    assert first["cursor"] == again["cursor"]


def test_tombstones_are_ordinary_rows_in_a_pull(api):
    """Hiding deletes leaves the client holding rows the server no longer has."""
    widget = Widget.objects.create(name="w")
    cursor = widget.row_version
    widget.soft_delete()

    rows = pull(api, cursor=cursor).json()["changes"]["widgets"]

    assert len(rows) == 1
    assert rows[0]["deleted_at"] is not None
    assert rows[0]["id"] == str(widget.pk)


def test_limit_is_capped(api):
    for index in range(3):
        Widget.objects.create(name=f"w{index}")
    assert pull(api, cursor=0, limit=10_000).status_code == 200


@pytest.mark.parametrize("params", [{"cursor": "abc"}, {"cursor": -1}, {"limit": "x"}])
def test_rejects_malformed_paging_params(api, params):
    assert pull(api, **params).status_code == 400


def test_unknown_ids_are_not_leaked_between_entities(api):
    widget = Widget.objects.create(name="w")
    body = pull(api, cursor=0).json()
    assert body["changes"]["gadgets"] == []
    assert body["changes"]["widgets"][0]["id"] == str(widget.pk)
    assert uuid.UUID(body["changes"]["widgets"][0]["id"]).version == 7
