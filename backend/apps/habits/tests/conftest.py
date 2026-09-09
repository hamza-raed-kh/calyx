from datetime import date, time

import pytest
from psycopg.types.range import Range

from apps.habits.enums import (
    ComponentMode,
    Frequency,
    PrayerKey,
    RolloverMode,
    SlotAnchor,
    WindowEndRule,
)
from apps.habits.models import (
    AppSettings,
    Habit,
    HabitComponent,
    HabitScheduleVersion,
    HabitSlot,
    Location,
    LocationPeriod,
)

MECCA = {
    "latitude": "21.389100",
    "longitude": "39.857900",
    "timezone": "Asia/Riyadh",
    "calc_method": "UMM_AL_QURA",
    "madhab": "SHAFI",
}

#: Ordered as the day runs, with the window end each prayer actually deserves.
#: Fajr ends at SUNRISE -- "until the next prayer" would score an 11am Fajr as
#: on time, which is the bug this table exists to prevent.
PRAYER_SLOTS = [
    ("fajr", "Fajr", PrayerKey.FAJR, WindowEndRule.SUNRISE),
    ("dhuhr", "Dhuhr", PrayerKey.DHUHR, WindowEndRule.NEXT_PRAYER),
    ("asr", "Asr", PrayerKey.ASR, WindowEndRule.NEXT_PRAYER),
    ("maghrib", "Maghrib", PrayerKey.MAGHRIB, WindowEndRule.NEXT_PRAYER),
    ("isha", "Isha", PrayerKey.ISHA, WindowEndRule.ISLAMIC_MIDNIGHT),
]


@pytest.fixture
def settings_row(db):
    row = AppSettings.get()
    row.timezone = "Asia/Riyadh"
    row.day_rollover = time(3, 0)
    row.save()
    return row


@pytest.fixture
def mecca(db):
    location = Location.objects.create(name="Mecca", **MECCA)
    LocationPeriod.objects.create(location=location, period=Range(None, None, "[)"))
    return location


def make_habit(key="thing", name=None, **kwargs) -> Habit:
    return Habit.objects.create(key=key, name=name or key.title(), **kwargs)


def add_schedule(
    habit,
    *,
    lower=None,
    upper=None,
    frequency=Frequency.DAILY,
    rollover_mode=RolloverMode.INHERIT,
    **kwargs,
) -> HabitScheduleVersion:
    return HabitScheduleVersion.objects.create(
        habit=habit,
        valid=Range(lower, upper, "[)"),
        frequency=frequency,
        rollover_mode=rollover_mode,
        **kwargs,
    )


def add_slot(version, key="default", label=None, **kwargs) -> HabitSlot:
    return HabitSlot.objects.create(
        schedule_version=version, key=key, label=label or key.title(), **kwargs
    )


def prayer_habit(rollover_mode=RolloverMode.FAJR) -> Habit:
    habit = make_habit("prayer", "Prayer")
    version = add_schedule(habit, rollover_mode=rollover_mode)
    for order, (key, label, prayer, end_rule) in enumerate(PRAYER_SLOTS):
        add_slot(
            version,
            key=key,
            label=label,
            sort_order=order,
            anchor=SlotAnchor.PRAYER,
            prayer_key=prayer,
            window_end_rule=end_rule,
        )
    return habit


def any_of_habit(key, components) -> Habit:
    habit = make_habit(key, component_mode=ComponentMode.ANY_OF)
    add_slot(add_schedule(habit))
    for order, (component_key, label) in enumerate(components):
        HabitComponent.objects.create(habit=habit, key=component_key, label=label, sort_order=order)
    return habit


def weekly_habit(key="piano", times=3) -> Habit:
    habit = make_habit(key)
    version = add_schedule(habit, frequency=Frequency.TIMES_PER_WEEK, times_per_week=times)
    add_slot(version)
    return habit


DAY = date(2026, 6, 21)
