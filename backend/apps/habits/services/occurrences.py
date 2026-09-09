"""Occurrence generation.

There is no HabitOccurrence table. An occurrence is produced on demand from the
schedule version that was valid on the day in question. That is what makes
backfill work for any date, makes unarchiving a habit produce no phantom misses,
and removes the need for a generation job that must never fail.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from datetime import date as date_cls
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..enums import Frequency, Requirement, RolloverMode, SlotAnchor, WindowEndRule
from ..models import (
    AppSettings,
    Habit,
    HabitScheduleVersion,
    Location,
    LocationPeriod,
    PrayerTimeDay,
)
from . import prayer_times as pt

UTC = UTC


# --- wall-clock resolution ---------------------------------------------------


def resolve_wall(tz: ZoneInfo, day: date_cls, wall: time) -> datetime:
    """Resolve a local wall-clock time to a UTC instant, DST-safe.

    Two irregular cases, both handled so that day boundaries stay monotonic --
    which is the property everything downstream depends on:

    * Spring-forward gap: the wall time never happens. Snap to the transition
      instant. Naively taking fold=0 would map 02:30 to a LATER instant than
      03:00, which breaks ordering.
    * Fall-back ambiguity: the wall time happens twice. Take the earlier one.
    """
    naive = datetime.combine(day, wall)
    earlier = naive.replace(tzinfo=tz, fold=0)
    later = naive.replace(tzinfo=tz, fold=1)

    earlier_offset, later_offset = earlier.utcoffset(), later.utcoffset()
    if earlier_offset == later_offset:
        return earlier.astimezone(UTC)

    if earlier_offset > later_offset:
        # Ambiguous (clocks went back): the earlier occurrence.
        return earlier.astimezone(UTC)

    return _gap_transition(tz, naive, later.astimezone(UTC), earlier.astimezone(UTC))


def _gap_transition(tz: ZoneInfo, naive: datetime, low: datetime, high: datetime) -> datetime:
    """The instant a spring-forward gap ends.

    Binary search: local time is below `naive` before the transition and at or
    above it after, so the predicate flips exactly once.
    """
    while (high - low) > timedelta(seconds=1):
        middle = low + (high - low) / 2
        if middle.astimezone(tz).replace(tzinfo=None) < naive:
            low = middle
        else:
            high = middle
    return high.replace(microsecond=0)


# --- the occurrence ----------------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    id: str
    habit_id: str
    habit_key: str
    slot_key: str
    slot_label: str
    habit_day: date_cls
    day_start: datetime
    day_end: datetime
    window_start: datetime | None
    window_end: datetime | None
    requirement: str
    schedule_version_id: str | None = None
    location_id: str | None = None
    period_key: str | None = None
    period_target: int | None = None
    target_value: Decimal | None = None
    target_unit: str = ""
    notify_at: datetime | None = None
    remind_at: datetime | None = None

    def state(self, now: datetime) -> str:
        if self.window_start is None or self.window_end is None:
            return "unavailable"
        if now < self.window_start:
            return "upcoming"
        if now >= self.window_end:
            return "closed"
        return "open"


def iso_period_key(day: date_cls, week_starts_on: int) -> str:
    """Week label for TIMES_PER_WEEK habits, honouring a configurable week start."""
    shift = (day.weekday() - week_starts_on) % 7
    start = day - timedelta(days=shift)
    return f"{start.isoformat()}/P7D"


class OccurrenceGenerator:
    """Generates occurrences for a date range.

    Preloads settings, location periods and prayer rows once, so generating a
    90-day stats window is a handful of queries rather than one per day.
    """

    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings or AppSettings.get()
        self._periods = list(
            LocationPeriod.objects.live().select_related("location").order_by("period")
        )
        self._prayer_rows: dict[tuple[str, date_cls], PrayerTimeDay] = {}
        self._fallback_tz = ZoneInfo(self.settings.timezone)

    # --- location and timezone ---------------------------------------------

    def location_for(self, day: date_cls) -> Location | None:
        for period in self._periods:
            lower, upper = period.period.lower, period.period.upper
            if (lower is None or day >= lower) and (upper is None or day < upper):
                return period.location
        return None

    def tz_for(self, day: date_cls) -> ZoneInfo:
        location = self.location_for(day)
        return ZoneInfo(location.timezone) if location else self._fallback_tz

    # --- prayer rows --------------------------------------------------------

    def preload_prayer_times(self, start: date_cls, end: date_cls) -> None:
        """Fetch, and lazily compute, the rows the range needs.

        Reaches one day past `end` because Isha's window and a Fajr-anchored day
        boundary both need the following day's Fajr.
        """
        locations = {
            location.id: location
            for day in _days(start, end + timedelta(days=1))
            if (location := self.location_for(day)) is not None
        }
        if not locations:
            return

        for location in locations.values():
            pt.ensure_prayer_times(location, start, end + timedelta(days=1))

        rows = PrayerTimeDay.objects.filter(
            location_id__in=locations,
            solar_date__gte=start,
            solar_date__lte=end + timedelta(days=1),
        )
        for row in rows:
            self._prayer_rows[(str(row.location_id), row.solar_date)] = row

    def prayer_row(self, location: Location | None, day: date_cls) -> PrayerTimeDay | None:
        if location is None:
            return None
        return self._prayer_rows.get((str(location.id), day))

    # --- day boundaries -----------------------------------------------------

    def day_bounds(self, version: HabitScheduleVersion, day: date_cls) -> tuple[datetime, datetime]:
        """[start, end) for a habit-day.

        A habit-day is NOT 24 hours. Each boundary is resolved independently
        from wall time, so a DST day is 23 or 25 hours and a travel day is
        whatever the offset change makes it.
        """
        start = self._boundary(version, day)
        end = self._boundary(version, day + timedelta(days=1))
        if end <= start:
            # Pathological: a timezone change large enough to invert the day.
            # Degrade to something ordered rather than emitting a negative day.
            end = start + timedelta(hours=1)
        return start, end

    def _boundary(self, version: HabitScheduleVersion, day: date_cls) -> datetime:
        location = self.location_for(day)
        tz = ZoneInfo(location.timezone) if location else self._fallback_tz

        if version.rollover_mode == RolloverMode.FAJR:
            row = self.prayer_row(location, day)
            if row is not None and row.fajr_at is not None:
                return row.fajr_at
            # High latitude, or times not yet computed: fall back rather than fail.
            return resolve_wall(tz, day, self.settings.day_rollover)

        if version.rollover_mode == RolloverMode.FIXED and version.rollover_time:
            return resolve_wall(tz, day, version.rollover_time)

        return resolve_wall(tz, day, self.settings.day_rollover)

    # --- windows ------------------------------------------------------------

    def window_for(self, slot, day, day_start, day_end) -> tuple[datetime | None, datetime | None]:
        if slot.anchor == SlotAnchor.ALL_DAY:
            return day_start, day_end

        location = self.location_for(day)
        tz = ZoneInfo(location.timezone) if location else self._fallback_tz

        if slot.anchor == SlotAnchor.FIXED_TIME:
            start = resolve_wall(tz, day, slot.window_start_local)
            end = resolve_wall(
                tz, day + timedelta(days=slot.window_end_day_offset), slot.window_end_local
            )
            if end <= start:
                # An unflagged wrap past midnight, e.g. 20:00-03:00.
                end = resolve_wall(tz, day + timedelta(days=1), slot.window_end_local)
            return start, end

        # PRAYER
        row = self.prayer_row(location, day)
        if row is None:
            return None, None
        start = row.time_for(slot.prayer_key)
        if start is None:
            return None, None

        following = self.prayer_row(
            self.location_for(day + timedelta(days=1)), day + timedelta(days=1)
        )
        end = self._prayer_window_end(slot, row, following, start)
        if end is None or end <= start:
            # Degrade to the end of the day rather than emitting an inverted
            # window that would make every log read as "late".
            end = day_end
        return start, end

    def _prayer_window_end(self, slot, row, following, start):
        match slot.window_end_rule:
            case WindowEndRule.SUNRISE:
                return row.sunrise_at
            case WindowEndRule.ISLAMIC_MIDNIGHT:
                return row.islamic_midnight_at
            case WindowEndRule.FIXED_MINUTES:
                return start + timedelta(minutes=slot.window_end_minutes or 0)
            case _:
                return pt.next_prayer_after(row, slot.prayer_key, following)

    # --- generation ---------------------------------------------------------

    def generate(self, habit: Habit, start: date_cls, end: date_cls) -> list[Occurrence]:
        versions = [
            version
            for version in habit.versions.live().prefetch_related("slots")
            if _range_overlaps(version.valid, start, end)
        ]
        if not versions:
            return []

        out: list[Occurrence] = []
        for day in _days(start, end):
            version = _version_for(versions, day)
            if version is None:
                continue
            if habit.archived_at is not None and day > habit.archived_at.date():
                continue

            weekday = day.weekday()
            if version.days_of_week and weekday not in version.days_of_week:
                continue

            day_start, day_end = self.day_bounds(version, day)
            location = self.location_for(day)
            slots = [s for s in version.slots.all() if s.deleted_at is None]

            if version.frequency == Frequency.TIMES_PER_WEEK:
                slot = slots[0] if slots else None
                out.append(
                    self._occurrence(
                        habit,
                        version,
                        slot,
                        day,
                        day_start,
                        day_end,
                        day_start,
                        day_end,
                        Requirement.TOWARD_PERIOD,
                        location,
                        period_key=iso_period_key(
                            day,
                            version.week_starts_on
                            if version.week_starts_on is not None
                            else self.settings.week_starts_on,
                        ),
                        period_target=version.times_per_week,
                    )
                )
                continue

            for slot in sorted(slots, key=lambda s: (s.sort_order, s.key)):
                window_start, window_end = self.window_for(slot, day, day_start, day_end)
                requirement = (
                    Requirement.UNAVAILABLE if window_start is None else Requirement.REQUIRED
                )
                out.append(
                    self._occurrence(
                        habit,
                        version,
                        slot,
                        day,
                        day_start,
                        day_end,
                        window_start,
                        window_end,
                        requirement,
                        location,
                    )
                )
        return out

    def _occurrence(
        self,
        habit,
        version,
        slot,
        day,
        day_start,
        day_end,
        window_start,
        window_end,
        requirement,
        location,
        *,
        period_key=None,
        period_target=None,
    ) -> Occurrence:
        slot_key = slot.key if slot else "default"
        notify_at = remind_at = None
        if slot and window_start and slot.notify_offset_minutes is not None:
            notify_at = window_start + timedelta(minutes=slot.notify_offset_minutes)
        if slot and window_end and slot.remind_before_end_minutes is not None:
            remind_at = window_end - timedelta(minutes=slot.remind_before_end_minutes)

        return Occurrence(
            id=f"{habit.key}:{slot_key}:{day.isoformat()}",
            habit_id=str(habit.id),
            habit_key=habit.key,
            slot_key=slot_key,
            slot_label=slot.label if slot else habit.name,
            habit_day=day,
            day_start=day_start,
            day_end=day_end,
            window_start=window_start,
            window_end=window_end,
            requirement=requirement,
            schedule_version_id=str(version.id),
            location_id=str(location.id) if location else None,
            period_key=period_key,
            period_target=period_target,
            target_value=slot.target_value if slot else None,
            target_unit=slot.target_unit if slot else "",
            notify_at=notify_at,
            remind_at=remind_at,
        )

    def generate_all(self, start: date_cls, end: date_cls) -> list[Occurrence]:
        self.preload_prayer_times(start, end)
        habits = Habit.objects.live().prefetch_related("versions__slots")
        out: list[Occurrence] = []
        for habit in habits:
            out.extend(self.generate(habit, start, end))
        return out


# --- helpers -----------------------------------------------------------------


def _days(start: date_cls, end: date_cls):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _range_overlaps(valid, start: date_cls, end: date_cls) -> bool:
    lower, upper = valid.lower, valid.upper
    if upper is not None and upper <= start:
        return False
    return not (lower is not None and lower > end)


def _version_for(versions, day: date_cls):
    for version in versions:
        lower, upper = version.valid.lower, version.valid.upper
        if (lower is None or day >= lower) and (upper is None or day < upper):
            return version
    return None
