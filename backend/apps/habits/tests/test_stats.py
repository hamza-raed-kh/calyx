from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.habits.enums import EntryMode, LogStatus
from apps.habits.models import HabitComponent, HabitLog
from apps.habits.services.logging import classify, record, resolve
from apps.habits.services.occurrences import OccurrenceGenerator
from apps.habits.services.stats import StatsCalculator, heatmap, satisfied

from .conftest import add_schedule, add_slot, any_of_habit, make_habit, prayer_habit, weekly_habit

pytestmark = pytest.mark.django_db

RIYADH = ZoneInfo("Asia/Riyadh")
BASE = date(2026, 7, 6)  # a Monday
# Each "now" is chosen so the days under test are fully elapsed and nothing
# else is. A rate is only meaningful against a denominator you control.
NOW = datetime(2026, 7, 7, 12, tzinfo=UTC)  # BASE elapsed, BASE+1 not
NOW_3DAY = datetime(2026, 7, 9, 12, tzinfo=UTC)
NOW_1WEEK = datetime(2026, 7, 13, 12, tzinfo=UTC)  # one whole week past BASE
NOW_2WEEK = datetime(2026, 7, 20, 12, tzinfo=UTC)  # two whole weeks past BASE


def occurrences_for(habit, start, end):
    generator = OccurrenceGenerator()
    generator.preload_prayer_times(start, end)
    return generator.generate(habit, start, end)


def log(occurrence, *, when=None, status=None, value=None, component=None):
    # Seed history the way it really accumulates -- each log written on the day
    # it happened -- rather than backfilling months at once, which the backfill
    # window quite rightly refuses.
    entry = record(
        occurrence,
        occurred_at=when,
        value=value,
        component=component,
        now=occurrence.day_end,
        entry_mode=EntryMode.LIVE,
    )
    if status is not None:
        HabitLog.objects.filter(pk=entry.pk).update(status=status)
        entry.refresh_from_db()
    return entry


def stats_for(habit, days=1, now=NOW):
    return StatsCalculator(now=now).for_habit(habit, days=days)


# --- the satisfaction rule ---------------------------------------------------


def test_two_partial_logs_add_up_to_a_target(settings_row, mecca):
    """SUM, not max: 10 pages this morning and 10 more tonight is 20 pages."""
    habit = make_habit("reading")
    add_slot(add_schedule(habit), target_value=20, target_unit="pages")
    occurrence = occurrences_for(habit, BASE, BASE)[0]

    first = log(occurrence, value=Decimal(10))
    assert satisfied(occurrence, [first]) is False

    second = log(occurrence, value=Decimal(10))
    assert satisfied(occurrence, [first, second]) is True


def test_a_single_log_satisfies_an_untargeted_habit(settings_row, mecca):
    """'At least one gaming session' needs no special case."""
    habit = make_habit("gaming")
    add_slot(add_schedule(habit))
    occurrence = occurrences_for(habit, BASE, BASE)[0]
    assert satisfied(occurrence, [log(occurrence)]) is True


def test_a_tombstoned_log_stops_counting(settings_row, mecca):
    habit = make_habit("walk")
    add_slot(add_schedule(habit))
    occurrence = occurrences_for(habit, BASE, BASE)[0]
    entry = log(occurrence)
    entry.soft_delete()
    assert satisfied(occurrence, [entry]) is False


# --- multi-slot: partial, not binary ----------------------------------------


def test_four_of_five_prayers_scores_eighty_percent(settings_row, mecca):
    """Binary scoring would make 4/5 identical to 0/5, destroying exactly the
    signal the per-slot report exists to provide."""
    habit = prayer_habit()
    day_occurrences = occurrences_for(habit, BASE, BASE)
    for occurrence in day_occurrences[:4]:
        log(occurrence, when=occurrence.window_start + timedelta(minutes=5))

    stats = stats_for(habit)

    assert stats.expected_slots == 5
    assert stats.satisfied_slots == 4
    assert stats.slot_rate == 0.8
    assert stats.perfect_day_rate == 0.0


def test_the_per_slot_breakdown_names_the_prayer_you_miss(settings_row, mecca):
    habit = prayer_habit()
    for day_offset in range(3):
        day = BASE + timedelta(days=day_offset)
        for occurrence in occurrences_for(habit, day, day):
            if occurrence.slot_key == "fajr":
                continue  # the one consistently missed
            log(occurrence, when=occurrence.window_start + timedelta(minutes=5))

    stats = stats_for(habit, days=3, now=NOW_3DAY)
    by_key = {slot.key: slot for slot in stats.by_slot}

    assert by_key["fajr"].satisfied == 0
    assert by_key["fajr"].missed == 3
    assert by_key["dhuhr"].rate == 1.0


# --- punctuality is separate from completion --------------------------------


def test_late_still_counts_as_completed(settings_row, mecca):
    habit = prayer_habit()
    occurrence = next(o for o in occurrences_for(habit, BASE, BASE) if o.slot_key == "fajr")
    entry = log(occurrence, when=occurrence.window_end + timedelta(hours=2))

    assert entry.status == LogStatus.LATE
    stats = stats_for(habit)
    assert stats.satisfied_slots == 1
    assert stats.punctuality_rate == 0.0


def test_an_untimed_backfill_counts_but_is_not_judged(settings_row, mecca):
    """Otherwise filling in yesterday either flatters or punishes you."""
    habit = prayer_habit()
    occurrence = next(o for o in occurrences_for(habit, BASE, BASE) if o.slot_key == "fajr")
    entry = log(occurrence, when=None)

    assert entry.status == LogStatus.UNKNOWN
    stats = stats_for(habit)
    assert stats.satisfied_slots == 1
    assert stats.unknown == 1
    assert stats.punctuality_rate is None  # nothing judged, so no rate


def test_punctuality_mixes_only_judged_logs(settings_row, mecca):
    habit = prayer_habit()
    day_occurrences = occurrences_for(habit, BASE, BASE)
    log(day_occurrences[0], when=day_occurrences[0].window_start + timedelta(minutes=1))
    log(day_occurrences[1], when=day_occurrences[1].window_end + timedelta(minutes=1))
    log(day_occurrences[2], when=None)

    stats = stats_for(habit)
    assert (stats.on_time, stats.late, stats.unknown) == (1, 1, 1)
    assert stats.punctuality_rate == 0.5


# --- the denominator rule ----------------------------------------------------


def test_today_is_excluded_from_the_denominator(settings_row, mecca):
    """Including the in-progress day craters every rate each morning."""
    habit = make_habit("walk")
    add_slot(add_schedule(habit))

    today = NOW.astimezone(RIYADH).date()
    stats = stats_for(habit, days=3)

    assert stats.window_end < today
    assert stats.eligible_days == 3


def test_eligible_days_is_reported_so_a_rate_cannot_mislead(settings_row, mecca):
    """83% of 12 days is a different claim from 83% of 90."""
    habit = make_habit("walk")
    add_schedule(habit, lower=BASE)
    add_slot(habit.versions.first())

    stats = stats_for(habit, days=90)
    assert stats.eligible_days < 90
    assert stats.window_start == BASE


# --- times per week ----------------------------------------------------------


def test_two_of_three_sessions_scores_sixty_seven_percent(settings_row, mecca):
    """Period-binary scoring would call this a zero, which is the all-or-nothing
    framing the owner explicitly rejected."""
    habit = weekly_habit(times=3)
    week = occurrences_for(habit, BASE, BASE + timedelta(days=6))
    for occurrence in week[:2]:
        log(occurrence)

    stats = stats_for(habit, days=7, now=NOW_1WEEK)
    assert len(stats.periods) == 1
    assert stats.periods[0].sessions == 2
    assert stats.period_rate == round(2 / 3, 4)


def test_a_big_week_cannot_paper_over_an_empty_one(settings_row, mecca):
    habit = weekly_habit(times=3)
    first = occurrences_for(habit, BASE, BASE + timedelta(days=6))
    for occurrence in first[:6]:  # six sessions in one week
        log(occurrence)

    stats = stats_for(habit, days=14, now=NOW_2WEEK)  # two whole weeks, second empty
    assert len(stats.periods) == 2
    busy = max(stats.periods, key=lambda period: period.sessions)
    assert busy.sessions == 6
    assert busy.counted == 3  # capped, so the empty week still drags the rate down
    assert stats.period_rate == 0.5


def test_the_in_progress_week_is_reported_separately_not_scored(settings_row, mecca):
    habit = weekly_habit(times=3)
    stats = stats_for(habit, days=7, now=NOW_1WEEK)

    assert stats.current_period is not None
    assert stats.current_period["target"] == 3
    assert stats.current_period["days_left"] > 0
    assert all(period.key != stats.current_period["key"] for period in stats.periods)


# --- components --------------------------------------------------------------


def test_either_component_satisfies_and_the_mix_is_recorded(settings_row, mecca):
    habit = any_of_habit("quran", [("read", "Read"), ("listen", "Listen")])
    read = HabitComponent.objects.get(habit=habit, key="read")
    listen = HabitComponent.objects.get(habit=habit, key="listen")

    log(occurrences_for(habit, BASE, BASE)[0], component=read)
    day2 = BASE + timedelta(days=1)
    log(occurrences_for(habit, day2, day2)[0], component=listen)

    stats = stats_for(habit, days=3, now=NOW_3DAY)
    assert stats.satisfied_slots == 2
    assert stats.component_mix == {"read": 1, "listen": 1}


# --- classification ----------------------------------------------------------


def test_classify_boundaries(settings_row, mecca):
    occurrence = next(
        o for o in occurrences_for(prayer_habit(), BASE, BASE) if o.slot_key == "fajr"
    )

    assert classify(occurrence, occurrence.window_start) == LogStatus.ON_TIME
    assert classify(occurrence, occurrence.window_start - timedelta(minutes=1)) == LogStatus.EARLY
    # The end is exclusive: at the instant the window closes you are late.
    assert classify(occurrence, occurrence.window_end) == LogStatus.LATE
    assert classify(occurrence, None) == LogStatus.UNKNOWN


def test_resolve_rebuilds_an_occurrence_from_its_id(settings_row, mecca):
    prayer_habit()
    occurrence = resolve(f"prayer:asr:{BASE.isoformat()}")
    assert occurrence.slot_key == "asr"
    assert occurrence.habit_day == BASE


def test_backfill_beyond_the_window_is_refused(settings_row, mecca):
    from apps.habits.services.logging import BackfillTooOld

    habit = make_habit("walk")
    add_slot(add_schedule(habit))
    old = NOW.date() - timedelta(days=30)
    occurrence = occurrences_for(habit, old, old)[0]

    with pytest.raises(BackfillTooOld):
        record(occurrence, occurred_at=None, now=NOW)


# --- heatmap -----------------------------------------------------------------


def test_heatmap_reports_a_fraction_per_day(settings_row, mecca):
    from apps.habits.models import Habit

    habit = prayer_habit()
    for occurrence in occurrences_for(habit, BASE, BASE)[:3]:
        log(occurrence, when=occurrence.window_start + timedelta(minutes=1))

    cells = heatmap(Habit.objects.live(), BASE, BASE, now=NOW)
    assert cells[0]["expected"] == 5
    assert cells[0]["satisfied"] == 3
    assert cells[0]["fraction"] == 0.6
