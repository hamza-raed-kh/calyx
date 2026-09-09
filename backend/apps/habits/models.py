"""Habit engine schema.

Two ideas carry the whole design:

1. Occurrences are COMPUTED, never stored. What is materialised is the expensive
   astronomical input (PrayerTimeDay), not the expectation derived from it.
2. Schedules are TEMPORALLY VERSIONED. That is what makes (1) safe once history
   exists: "which schedule applied on 2026-06-14?" is answerable by construction.
"""

import hashlib
import json
from datetime import time

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateRangeField, RangeOperators
from django.db import models

from apps.core.models import SyncableModel

from .enums import (
    CalcMethod,
    ComponentMode,
    EntryMode,
    Frequency,
    HighLatitudeRule,
    LogStatus,
    Madhab,
    PrayerKey,
    RolloverMode,
    SlotAnchor,
    WindowEndRule,
)


class AppSettings(SyncableModel):
    """Singleton. The app is single-user; there is no owner FK anywhere."""

    singleton = models.PositiveSmallIntegerField(default=1, unique=True)

    timezone = models.CharField(max_length=64, default="UTC")

    # Not midnight. A day that ends at 03:00 keeps a 01:00 log on the evening it
    # belongs to, and sits in the dead zone between Isha and Fajr.
    day_rollover = models.TimeField(default=time(3, 0))

    backfill_days = models.PositiveSmallIntegerField(default=7)
    week_starts_on = models.SmallIntegerField(default=0)  # 0=Mon .. 6=Sun
    prefetch_horizon_days = models.PositiveSmallIntegerField(default=35)

    class Meta:
        verbose_name_plural = "app settings"
        constraints = [
            models.CheckConstraint(condition=models.Q(singleton=1), name="appsettings_singleton"),
            models.CheckConstraint(
                condition=models.Q(week_starts_on__gte=0, week_starts_on__lte=6),
                name="appsettings_week_start_in_range",
            ),
        ]

    @classmethod
    def get(cls) -> "AppSettings":
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj


class Location(SyncableModel):
    """Where prayer times are computed for.

    Treated as immutable: changing madhab or calculation method CLONES a
    Location and opens a new LocationPeriod rather than editing in place. An
    in-place edit would retroactively rewrite every historical Asr.
    """

    name = models.CharField(max_length=64)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timezone = models.CharField(max_length=64)
    elevation_m = models.SmallIntegerField(default=0)

    calc_method = models.CharField(
        max_length=32, choices=CalcMethod.choices, default=CalcMethod.UMM_AL_QURA
    )
    madhab = models.CharField(max_length=8, choices=Madhab.choices, default=Madhab.SHAFI)
    high_latitude_rule = models.CharField(
        max_length=24,
        choices=HighLatitudeRule.choices,
        default=HighLatitudeRule.MIDDLE_OF_THE_NIGHT,
    )
    #: Per-prayer minute offsets, e.g. {"fajr": -2, "isha": 3}
    adjustments = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.name

    def params_hash(self) -> str:
        """Fingerprint of everything that affects a computed time.

        Stamped onto every PrayerTimeDay so a row computed under stale
        parameters is detectable rather than silently wrong.
        """
        payload = json.dumps(
            {
                "lat": str(self.latitude),
                "lon": str(self.longitude),
                "tz": self.timezone,
                "elevation": self.elevation_m,
                "method": self.calc_method,
                "madhab": self.madhab,
                "high_latitude_rule": self.high_latitude_rule,
                "adjustments": self.adjustments or {},
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class LocationPeriod(SyncableModel):
    """Where the owner was, in habit-date terms. Also supplies the timezone.

    Spending a month elsewhere should move the day boundary too, not just the
    prayer times.
    """

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="periods")
    #: [start, end) in local habit-dates. Unbounded upper = current.
    period = DateRangeField()
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="locationperiod_no_overlap",
                expressions=[("period", RangeOperators.OVERLAPS)],
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]


class PrayerTimeDay(SyncableModel):
    """Materialised astronomical input. One wide row per location per solar date.

    Wide rather than tall because chaining a window to "the next prayer" needs
    sibling times in the same fetch, and Isha needs *tomorrow's* Fajr.

    Nullable times are deliberate: at extreme latitude the solver can fail to
    produce Fajr or Isha, and the engine must degrade rather than crash.
    """

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="prayer_days")
    solar_date = models.DateField()

    fajr_at = models.DateTimeField(null=True)
    sunrise_at = models.DateTimeField(null=True)
    dhuhr_at = models.DateTimeField(null=True)
    asr_at = models.DateTimeField(null=True)
    maghrib_at = models.DateTimeField(null=True)
    isha_at = models.DateTimeField(null=True)
    #: Midpoint between Maghrib and the next Fajr.
    islamic_midnight_at = models.DateTimeField(null=True)

    params_hash = models.CharField(max_length=64)
    engine_version = models.CharField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "solar_date"], name="prayertimeday_unique_per_location_date"
            )
        ]
        indexes = [models.Index(fields=["location", "solar_date"])]
        ordering = ["solar_date"]

    def time_for(self, prayer: str):
        return getattr(self, f"{prayer.lower()}_at")


class Habit(SyncableModel):
    key = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    icon = models.CharField(max_length=32, blank=True)
    color = models.CharField(max_length=9, blank=True)

    component_mode = models.CharField(
        max_length=8, choices=ComponentMode.choices, default=ComponentMode.NONE
    )
    requires_project = models.BooleanField(default=False)
    allows_project = models.BooleanField(default=False)

    sort_order = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    #: Archived is not deleted: history stays, the denominator simply stops.
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class HabitScheduleVersion(SyncableModel):
    """A habit's schedule, valid over a date range.

    Everything schedule-shaped lives here rather than on Habit, because
    everything schedule-shaped can be edited and must not corrupt history.
    """

    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name="versions")
    #: [effective_from, effective_to) in local habit-dates.
    valid = DateRangeField()

    frequency = models.CharField(max_length=16, choices=Frequency.choices, default=Frequency.DAILY)
    times_per_week = models.PositiveSmallIntegerField(null=True, blank=True)
    week_starts_on = models.SmallIntegerField(null=True, blank=True)
    #: Optional eligibility restriction, 0=Mon..6=Sun. Null means every day.
    days_of_week = ArrayField(models.SmallIntegerField(), null=True, blank=True)

    rollover_mode = models.CharField(
        max_length=8, choices=RolloverMode.choices, default=RolloverMode.INHERIT
    )
    rollover_time = models.TimeField(null=True, blank=True)

    change_reason = models.CharField(max_length=140, blank=True)

    class Meta:
        ordering = ["habit", "valid"]
        constraints = [
            ExclusionConstraint(
                name="schedule_version_no_overlap",
                expressions=[("habit", RangeOperators.EQUAL), ("valid", RangeOperators.OVERLAPS)],
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.CheckConstraint(
                condition=~models.Q(frequency=Frequency.TIMES_PER_WEEK)
                | models.Q(times_per_week__gte=1),
                name="times_per_week_required_when_weekly",
            ),
            models.CheckConstraint(
                condition=~models.Q(rollover_mode=RolloverMode.FIXED)
                | models.Q(rollover_time__isnull=False),
                name="fixed_rollover_needs_a_time",
            ),
        ]


class HabitSlot(SyncableModel):
    """One expectation within a habit-day.

    The slot, not the habit, is the atomic unit. One Prayer habit has five
    slots; one Brush teeth habit has two. Per-slot statistics -- "which prayer do
    I actually miss" -- then fall out of a GROUP BY rather than being a feature.
    """

    schedule_version = models.ForeignKey(
        HabitScheduleVersion, on_delete=models.CASCADE, related_name="slots"
    )
    #: STABLE ACROSS VERSIONS. This is the statistics identity; renaming it
    #: orphans history, whereas changing `label` is free.
    key = models.SlugField(max_length=24)
    label = models.CharField(max_length=40)
    sort_order = models.SmallIntegerField(default=0)

    anchor = models.CharField(max_length=12, choices=SlotAnchor.choices, default=SlotAnchor.ALL_DAY)

    window_start_local = models.TimeField(null=True, blank=True)
    window_end_local = models.TimeField(null=True, blank=True)
    #: 1 when the window closes on the following calendar day (e.g. 20:00-03:00).
    window_end_day_offset = models.SmallIntegerField(default=0)

    # NULL rather than "" on purpose: a non-prayer slot genuinely has no prayer,
    # and the check constraints below key on __isnull. An empty string would be
    # a second spelling of absent.
    prayer_key = models.CharField(  # noqa: DJ001
        max_length=8, choices=PrayerKey.choices, null=True, blank=True
    )
    window_end_rule = models.CharField(  # noqa: DJ001
        max_length=20, choices=WindowEndRule.choices, null=True, blank=True
    )
    window_end_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    target_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    target_unit = models.CharField(max_length=16, blank=True)

    notify_offset_minutes = models.SmallIntegerField(null=True, blank=True)
    remind_before_end_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule_version", "key"],
                name="slot_key_unique_per_version",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.CheckConstraint(
                condition=~models.Q(anchor=SlotAnchor.FIXED_TIME)
                | (
                    models.Q(window_start_local__isnull=False)
                    & models.Q(window_end_local__isnull=False)
                ),
                name="fixed_slot_needs_a_window",
            ),
            models.CheckConstraint(
                condition=~models.Q(anchor=SlotAnchor.PRAYER)
                | (models.Q(prayer_key__isnull=False) & models.Q(window_end_rule__isnull=False)),
                name="prayer_slot_needs_key_and_end_rule",
            ),
        ]


class HabitComponent(SyncableModel):
    """An alternative way of satisfying a habit (Quran: read or listen).

    Hangs off Habit rather than the schedule version, because components are not
    a scheduling concept. The component is RECORDED, not required -- which is why
    any-of habits need no special path through the generator at all.
    """

    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name="components")
    key = models.SlugField(max_length=24)
    label = models.CharField(max_length=40)
    sort_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["habit", "key"],
                name="component_key_unique_per_habit",
                condition=models.Q(deleted_at__isnull=True),
            )
        ]


class HabitLog(SyncableModel):
    """A thing that happened. An event, not a state.

    There is deliberately NO unique constraint on (habit, slot_key, habit_day).
    Completion is derived by aggregation, which is what makes "10 pages now, 10
    more tonight", "at least one gaming session", five prayers a day and two
    brushings all fall out of one rule instead of four special cases.
    """

    habit = models.ForeignKey(Habit, on_delete=models.PROTECT, related_name="logs")
    #: Denormalised, NOT an FK: slots are owned by a schedule version and are
    #: recreated on every edit, but the key is the stable statistics identity.
    slot_key = models.CharField(max_length=24)
    habit_day = models.DateField()
    occurred_at = models.DateTimeField()

    component = models.ForeignKey(
        HabitComponent, on_delete=models.PROTECT, null=True, blank=True, related_name="logs"
    )
    project = models.ForeignKey(
        "tasks.Project", on_delete=models.PROTECT, null=True, blank=True, related_name="habit_logs"
    )

    value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=16, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)

    # --- frozen judgment: written once, never recomputed ---------------------
    # Correcting your location or calculation method later must not silently
    # rewrite a punctuality claim you already made.
    status = models.CharField(max_length=8, choices=LogStatus.choices, default=LogStatus.UNKNOWN)
    window_start_at = models.DateTimeField(null=True, blank=True)
    window_end_at = models.DateTimeField(null=True, blank=True)
    schedule_version = models.ForeignKey(
        HabitScheduleVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="logs"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="logs"
    )

    entry_mode = models.CharField(max_length=8, choices=EntryMode.choices, default=EntryMode.LIVE)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["habit", "habit_day"]),
            models.Index(fields=["habit_day"]),
            models.Index(fields=["habit", "slot_key", "habit_day"]),
        ]
