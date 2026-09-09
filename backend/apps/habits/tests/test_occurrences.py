from datetime import date, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from apps.habits.enums import Requirement, RolloverMode, SlotAnchor
from apps.habits.services.occurrences import (
    OccurrenceGenerator,
    iso_period_key,
    resolve_wall,
)

from .conftest import DAY, add_schedule, add_slot, make_habit, prayer_habit, weekly_habit

pytestmark = pytest.mark.django_db

RIYADH = ZoneInfo("Asia/Riyadh")
NEW_YORK = ZoneInfo("America/New_York")


def generate(habit, start=DAY, end=None):
    generator = OccurrenceGenerator()
    generator.preload_prayer_times(start, end or start)
    return generator.generate(habit, start, end or start)


# --- wall clock and DST ------------------------------------------------------


def test_resolve_wall_is_exact_when_unambiguous():
    resolved = resolve_wall(RIYADH, date(2026, 6, 21), time(3, 0))
    assert resolved.astimezone(RIYADH).hour == 3


def test_spring_forward_gap_snaps_to_the_transition_instant():
    """02:30 does not exist on this date in New York.

    Taking fold=0 would map it to 03:30 -- LATER than 03:00 maps to -- which
    breaks the ordering every day boundary depends on.
    """
    gap = resolve_wall(NEW_YORK, date(2026, 3, 8), time(2, 30))
    after_gap = resolve_wall(NEW_YORK, date(2026, 3, 8), time(3, 0))
    before_gap = resolve_wall(NEW_YORK, date(2026, 3, 8), time(1, 59))

    assert before_gap < gap <= after_gap
    assert gap == after_gap


def test_fall_back_ambiguity_takes_the_earlier_occurrence():
    """01:30 happens twice on this date; the first is the one that counts."""
    resolved = resolve_wall(NEW_YORK, date(2026, 11, 1), time(1, 30))
    later = resolve_wall(NEW_YORK, date(2026, 11, 1), time(2, 30))
    assert resolved < later
    assert resolved.astimezone(NEW_YORK).utcoffset() == timedelta(hours=-4)  # still EDT


def test_a_spring_forward_habit_day_is_23_hours(settings_row):
    settings_row.timezone = "America/New_York"
    settings_row.save()
    habit = make_habit("walk")
    add_slot(add_schedule(habit))

    generator = OccurrenceGenerator()
    version = habit.versions.first()
    # The short day is the one that CONTAINS the 02:00 transition: it runs from
    # 03:00 on the 7th to 03:00 on the 8th, losing an hour on the way.
    start, end = generator.day_bounds(version, date(2026, 3, 7))

    assert end - start == timedelta(hours=23)


def test_a_fall_back_habit_day_is_25_hours(settings_row):
    settings_row.timezone = "America/New_York"
    settings_row.save()
    habit = make_habit("walk")
    add_slot(add_schedule(habit))

    generator = OccurrenceGenerator()
    start, end = generator.day_bounds(habit.versions.first(), date(2026, 10, 31))

    assert end - start == timedelta(hours=25)


def test_day_boundaries_stay_ordered_across_a_transition(settings_row):
    """The property everything downstream relies on."""
    settings_row.timezone = "America/New_York"
    settings_row.save()
    habit = make_habit("walk")
    add_slot(add_schedule(habit))
    generator = OccurrenceGenerator()
    version = habit.versions.first()

    starts = [
        generator.day_bounds(version, date(2026, 3, 6) + timedelta(days=i))[0] for i in range(5)
    ]
    assert starts == sorted(starts)


# --- prayer windows ----------------------------------------------------------


def test_five_prayers_appear_exactly_once_each(settings_row, mecca):
    occurrences = generate(prayer_habit())
    assert [o.slot_key for o in occurrences] == ["fajr", "dhuhr", "asr", "maghrib", "isha"]


def test_fajr_window_ends_at_sunrise_not_at_dhuhr(settings_row, mecca):
    """'Until the next prayer' is right for Dhuhr, Asr and Maghrib and wrong for
    Fajr: it would score an 11am Fajr as on time."""
    occurrences = {o.slot_key: o for o in generate(prayer_habit())}
    fajr = occurrences["fajr"]

    local_end = fajr.window_end.astimezone(RIYADH)
    assert local_end.hour == 5  # sunrise, not the 12:22 Dhuhr
    assert fajr.window_end < occurrences["dhuhr"].window_start


def test_isha_window_ends_at_islamic_midnight(settings_row, mecca):
    occurrences = {o.slot_key: o for o in generate(prayer_habit())}
    isha = occurrences["isha"]

    local_end = isha.window_end.astimezone(RIYADH)
    assert local_end.hour == 23  # midpoint of Maghrib and next Fajr
    assert isha.window_end > isha.window_start


def test_prayer_windows_are_contiguous_and_ordered(settings_row, mecca):
    occurrences = generate(prayer_habit())
    starts = [o.window_start for o in occurrences]
    assert starts == sorted(starts)
    for earlier, later in pairwise(occurrences[1:5]):
        assert earlier.window_end <= later.window_start


# --- the double-Fajr bug -----------------------------------------------------


def test_a_prayer_before_the_rollover_does_not_duplicate_or_vanish(settings_row, mecca):
    """With a rollover LATER than Fajr, the naive wall-clock rule would file two
    Fajrs onto one habit-day and none onto the next. The occurrence's habit_day
    comes from its solar date instead, so it cannot."""
    settings_row.day_rollover = time(5, 0)  # Mecca Fajr on this date is 04:11
    settings_row.save()

    habit = prayer_habit(rollover_mode=RolloverMode.INHERIT)
    occurrences = generate(habit, DAY, DAY + timedelta(days=2))
    fajrs = [o for o in occurrences if o.slot_key == "fajr"]

    assert len(fajrs) == 3
    assert [o.habit_day for o in fajrs] == [DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)]
    # The window legitimately opens before the day does; nothing may assert
    # containment.
    assert fajrs[0].window_start < fajrs[0].day_start


def test_fajr_anchoring_makes_the_day_start_at_fajr(settings_row, mecca):
    habit = prayer_habit(rollover_mode=RolloverMode.FAJR)
    occurrences = {o.slot_key: o for o in generate(habit)}

    assert occurrences["fajr"].day_start == occurrences["fajr"].window_start
    for occurrence in occurrences.values():
        assert occurrence.day_start <= occurrence.window_start < occurrence.day_end


# --- schedule shapes ---------------------------------------------------------


def test_multiple_slots_per_day(settings_row, mecca):
    habit = make_habit("teeth")
    version = add_schedule(habit)
    add_slot(
        version,
        "morning",
        anchor=SlotAnchor.FIXED_TIME,
        window_start_local=time(6),
        window_end_local=time(12),
        sort_order=0,
    )
    add_slot(
        version,
        "evening",
        anchor=SlotAnchor.FIXED_TIME,
        window_start_local=time(20),
        window_end_local=time(3),
        window_end_day_offset=1,
        sort_order=1,
    )

    occurrences = generate(habit)
    assert [o.slot_key for o in occurrences] == ["morning", "evening"]
    evening = occurrences[1]
    assert evening.window_end > evening.window_start  # wraps past midnight


def test_times_per_week_emits_one_occurrence_per_day_toward_a_period(settings_row, mecca):
    monday = date(2026, 9, 7)
    occurrences = generate(weekly_habit(times=3), monday, monday + timedelta(days=6))

    assert len(occurrences) == 7
    assert {o.requirement for o in occurrences} == {Requirement.TOWARD_PERIOD}
    assert {o.period_target for o in occurrences} == {3}
    assert len({o.period_key for o in occurrences}) == 1  # Monday..Sunday is one week


def test_a_week_boundary_splits_the_period_key(settings_row, mecca):
    """A span crossing the configured week start must land in two periods."""
    sunday = date(2026, 9, 6)
    occurrences = generate(weekly_habit(times=3), sunday, sunday + timedelta(days=1))
    assert len({o.period_key for o in occurrences}) == 2


def test_days_of_week_restricts_eligibility(settings_row, mecca):
    habit = make_habit("work")
    version = add_schedule(habit, days_of_week=[0, 1, 2, 3, 4])  # weekdays
    add_slot(version)

    occurrences = generate(habit, date(2026, 9, 7), date(2026, 9, 13))  # Mon..Sun
    assert len(occurrences) == 5


def test_target_rides_on_the_slot(settings_row, mecca):
    habit = make_habit("reading")
    add_slot(add_schedule(habit), target_value=20, target_unit="pages")
    assert generate(habit)[0].target_value == 20


# --- versioning --------------------------------------------------------------


def test_a_day_uses_the_schedule_that_was_valid_then(settings_row, mecca):
    """Backfilling into a changed schedule must see the OLD slots and target."""
    habit = make_habit("reading")
    old = add_schedule(habit, upper=DAY, change_reason="original")
    add_slot(old, target_value=10, target_unit="pages")
    new = add_schedule(habit, lower=DAY, change_reason="raised the target")
    add_slot(new, target_value=20, target_unit="pages")

    before = generate(habit, DAY - timedelta(days=1))[0]
    after = generate(habit, DAY)[0]

    assert before.target_value == 10
    assert after.target_value == 20
    assert before.schedule_version_id == str(old.id)
    assert after.schedule_version_id == str(new.id)


def test_a_gap_between_versions_produces_no_occurrences(settings_row, mecca):
    """Archiving then unarchiving must not manufacture phantom misses."""
    habit = make_habit("piano")
    first = add_schedule(habit, upper=DAY)
    add_slot(first)
    second = add_schedule(habit, lower=DAY + timedelta(days=5))
    add_slot(second)

    occurrences = generate(habit, DAY, DAY + timedelta(days=4))
    assert occurrences == []


def test_archiving_stops_the_denominator(settings_row, mecca):
    from django.utils import timezone as dj_tz

    habit = make_habit("gaming")
    add_slot(add_schedule(habit))
    habit.archived_at = dj_tz.make_aware(
        __import__("datetime").datetime.combine(DAY, time(12)), RIYADH
    )
    habit.save()

    occurrences = generate(habit, DAY, DAY + timedelta(days=3))
    assert [o.habit_day for o in occurrences] == [DAY]


# --- period keys -------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "week_start", "expected_start"),
    [
        (date(2026, 9, 9), 0, date(2026, 9, 7)),  # Wed, weeks start Monday
        (date(2026, 9, 9), 6, date(2026, 9, 6)),  # Wed, weeks start Sunday
        (date(2026, 9, 7), 0, date(2026, 9, 7)),  # Monday is its own week start
    ],
)
def test_period_key_honours_the_configured_week_start(day, week_start, expected_start):
    assert iso_period_key(day, week_start).startswith(expected_start.isoformat())
