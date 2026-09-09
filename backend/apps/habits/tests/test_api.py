from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.habits.models import Habit, HabitLog
from apps.tasks.models import Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(db):
    call_command(
        "seed_habits", latitude=21.3891, longitude=39.8579, timezone="Asia/Riyadh", verbosity=0
    )


def agenda(api, **params):
    return api.get(reverse("habits:agenda"), params)


# --- agenda ------------------------------------------------------------------


def test_agenda_requires_authentication(anon):
    assert anon.get(reverse("habits:agenda")).status_code in (401, 403)


def test_agenda_lists_every_expected_slot(api, seeded):
    body = agenda(api).json()
    keys = {(row["habit"]["key"], row["slot"]["key"]) for row in body["occurrences"]}

    # Five prayers plus two brushings plus the seven single-slot dailies.
    assert ("prayer", "fajr") in keys
    assert ("prayer", "isha") in keys
    assert ("teeth", "morning") in keys and ("teeth", "evening") in keys
    assert len([k for k in keys if k[0] == "prayer"]) == 5


def test_agenda_orders_by_window_so_the_day_reads_in_sequence(api, seeded):
    rows = agenda(api).json()["occurrences"]
    prayers = [r for r in rows if r["habit"]["key"] == "prayer"]
    assert [p["slot"]["key"] for p in prayers] == ["fajr", "dhuhr", "asr", "maghrib", "isha"]


def test_agenda_separates_flexible_habits_from_required_ones(api, seeded):
    body = agenda(api).json()
    flexible_keys = {row["habit"]["key"] for row in body["flexible"]}
    required_keys = {row["habit"]["key"] for row in body["occurrences"]}

    assert "piano" in flexible_keys
    assert "piano" not in required_keys


def test_agenda_reports_a_backfill_floor(api, seeded):
    body = agenda(api).json()
    floor = date.fromisoformat(body["backfill_floor"])
    assert date.fromisoformat(body["habit_day"]) - floor == timedelta(days=7)


def test_agenda_exposes_components_for_any_of_habits(api, seeded):
    rows = {row["habit"]["key"]: row for row in agenda(api).json()["occurrences"]}
    quran = rows["quran"]

    assert quran["habit"]["component_mode"] == "ANY_OF"
    assert {c["key"] for c in quran["components"]} == {"read", "listen"}


def test_agenda_rejects_a_malformed_date(api, seeded):
    assert agenda(api, date="not-a-date").status_code == 400


def test_agenda_accepts_an_explicit_day(api, seeded):
    body = agenda(api, date="2026-06-21").json()
    assert body["habit_day"] == "2026-06-21"


# --- logging -----------------------------------------------------------------


def log(api, **payload):
    return api.post(reverse("habits:create-log"), payload, format="json")


def today_for(api, habit_key, slot_key="default"):
    rows = agenda(api).json()["occurrences"]
    return next(r for r in rows if r["habit"]["key"] == habit_key and r["slot"]["key"] == slot_key)


def test_logging_records_and_freezes_the_window(api, seeded):
    row = today_for(api, "gaming")
    response = log(api, occurrence_id=row["id"])

    assert response.status_code == 201
    body = response.json()
    # The judgment is frozen onto the row so a later settings change cannot
    # rewrite a claim already made.
    assert body["window_start_at"] is not None
    assert body["window_end_at"] is not None
    assert body["status"] in {"ON_TIME", "LATE", "EARLY", "UNKNOWN"}


def test_logging_shows_up_in_the_next_agenda(api, seeded):
    row = today_for(api, "gaming")
    log(api, occurrence_id=row["id"])

    refreshed = today_for(api, "gaming")
    assert refreshed["progress"]["satisfied"] is True
    assert refreshed["progress"]["log_count"] == 1


def test_a_partial_value_does_not_satisfy_a_target(api, seeded):
    row = today_for(api, "reading")
    assert row["target"] == {"value": "20.00", "unit": "pages"}

    log(api, occurrence_id=row["id"], value="8")
    partial = today_for(api, "reading")
    assert partial["progress"]["satisfied"] is False

    log(api, occurrence_id=row["id"], value="12")
    complete = today_for(api, "reading")
    assert complete["progress"]["satisfied"] is True
    assert complete["progress"]["log_count"] == 2


def test_component_is_recorded_for_any_of_habits(api, seeded):
    row = today_for(api, "quran")
    response = log(api, occurrence_id=row["id"], component="listen")

    assert response.status_code == 201
    entry = HabitLog.objects.get(pk=response.json()["id"])
    assert entry.component.key == "listen"


def test_an_unknown_component_is_rejected(api, seeded):
    row = today_for(api, "quran")
    assert log(api, occurrence_id=row["id"], component="telepathy").status_code == 400


def test_a_habit_that_requires_a_project_refuses_without_one(api, seeded):
    row = today_for(api, "work")
    assert row["habit"]["requires_project"] is True
    assert log(api, occurrence_id=row["id"]).status_code == 400


def test_a_work_session_logs_against_a_project(api, seeded):
    project = Project.objects.create(name="Umbra")
    row = today_for(api, "work")

    response = log(api, occurrence_id=row["id"], project=str(project.id), duration_seconds=3600)

    assert response.status_code == 201
    assert HabitLog.objects.get(pk=response.json()["id"]).project_id == project.id


@pytest.mark.parametrize(
    "bad", ["", "prayer:fajr", "nope:fajr:2026-01-01", "prayer:zuhr:2026-01-01"]
)
def test_a_bad_occurrence_id_is_rejected(api, seeded, bad):
    assert log(api, occurrence_id=bad).status_code == 400


def test_backfill_beyond_the_window_is_refused(api, seeded):
    old = (datetime.now(UTC) - timedelta(days=40)).date()
    assert log(api, occurrence_id=f"gaming:default:{old.isoformat()}").status_code == 400


# --- stats -------------------------------------------------------------------


def test_rates_covers_every_habit_and_window(api, seeded):
    body = api.get(reverse("habits:rates"), {"windows": "7,30"}).json()
    keys = {entry["habit_key"] for entry in body["habits"]}

    assert keys == set(Habit.objects.values_list("key", flat=True))
    assert set(body["habits"][0]["windows"]) == {"7", "30"}


def test_rates_reports_eligible_days_so_a_percentage_cannot_mislead(api, seeded):
    body = api.get(reverse("habits:rates"), {"windows": "90"}).json()
    entry = next(e for e in body["habits"] if e["habit_key"] == "gaming")
    assert "eligible_days" in entry["windows"]["90"]


def test_rates_never_reports_a_streak(api, seeded):
    """Explicitly rejected; guard against it creeping back in."""
    body = api.get(reverse("habits:rates")).json()
    assert "streak" not in str(body).lower()


@pytest.mark.parametrize("bad", ["abc", "-1", "9999"])
def test_rates_rejects_bad_windows(api, seeded, bad):
    assert api.get(reverse("habits:rates"), {"windows": bad}).status_code == 400


def test_heatmap_returns_cells(api, seeded):
    row = today_for(api, "gaming")
    log(api, occurrence_id=row["id"])

    body = api.get(reverse("habits:heatmap"), {"from": "2026-01-01"}).json()
    assert isinstance(body["cells"], list)


def test_heatmap_rejects_an_inverted_range(api, seeded):
    response = api.get(reverse("habits:heatmap"), {"from": "2026-06-01", "to": "2026-01-01"})
    assert response.status_code == 400


# --- horizon -----------------------------------------------------------------


def test_horizon_expands_a_run_of_days(api, seeded):
    body = api.get(reverse("habits:horizon"), {"days": 5}).json()

    assert len(body["days"]) == 5
    assert [d["habit_day"] for d in body["days"]] == sorted(d["habit_day"] for d in body["days"])
    assert body["days"][0]["occurrences"], "each day must carry expanded occurrences"


def test_horizon_carries_notification_times_so_the_device_need_not_compute_them(api, seeded):
    body = api.get(reverse("habits:horizon"), {"days": 2}).json()
    prayers = [
        row
        for day in body["days"]
        for row in day["occurrences"]
        if row["habit"]["key"] == "prayer"
    ]
    assert prayers and all(row["notify_at"] for row in prayers)


@pytest.mark.parametrize("bad", ["0", "121", "abc"])
def test_horizon_rejects_an_unreasonable_span(api, seeded, bad):
    assert api.get(reverse("habits:horizon"), {"days": bad}).status_code == 400


def test_a_client_supplied_log_id_makes_logging_idempotent(api, seeded):
    """An offline log is queued with a client id and may arrive twice."""
    row = today_for(api, "gaming")
    log_id = "018f0000-0000-7000-8000-0000000f00d0"

    first = log(api, occurrence_id=row["id"], id=log_id)
    second = log(api, occurrence_id=row["id"], id=log_id)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"] == log_id
    assert HabitLog.objects.filter(habit__key="gaming").count() == 1
