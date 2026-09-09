"""Recording a habit log.

The judgment a log carries -- on time or late, and against which window -- is
computed once here and frozen onto the row. Correcting your location or
calculation method later must never silently rewrite a claim you already made.
"""

from datetime import date as date_cls
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from ..enums import EntryMode, LogStatus
from ..models import AppSettings, Habit, HabitLog
from .occurrences import Occurrence, OccurrenceGenerator


class BackfillTooOld(ValidationError):
    pass


class UnknownOccurrence(ValidationError):
    pass


def classify(occurrence: Occurrence, occurred_at: datetime | None) -> str:
    """On time, late, early, or unknown.

    UNKNOWN is a first-class outcome, not a failure: ticking "I did Fajr
    yesterday" without saying when must not fabricate an ON_TIME.
    """
    if occurred_at is None or occurrence.window_start is None or occurrence.window_end is None:
        return LogStatus.UNKNOWN
    if occurred_at < occurrence.window_start:
        return LogStatus.EARLY
    if occurred_at >= occurrence.window_end:
        return LogStatus.LATE
    return LogStatus.ON_TIME


def parse_occurrence_id(occurrence_id: str) -> tuple[str, str, date_cls]:
    try:
        habit_key, slot_key, day = occurrence_id.split(":")
        return habit_key, slot_key, date_cls.fromisoformat(day)
    except (ValueError, AttributeError) as exc:
        raise UnknownOccurrence(f"malformed occurrence id {occurrence_id!r}") from exc


def resolve(occurrence_id: str, *, generator: OccurrenceGenerator | None = None) -> Occurrence:
    """Regenerate exactly one occurrence from the schedule valid on its day.

    The client sends an id it derived locally; the server re-derives rather than
    trusting it, so a stale or hand-crafted id cannot invent a window.
    """
    habit_key, slot_key, day = parse_occurrence_id(occurrence_id)
    generator = generator or OccurrenceGenerator()

    habit = Habit.objects.live().filter(key=habit_key).first()
    if habit is None:
        raise UnknownOccurrence(f"no habit {habit_key!r}")

    generator.preload_prayer_times(day, day)
    for occurrence in generator.generate(habit, day, day):
        if occurrence.slot_key == slot_key:
            return occurrence
    raise UnknownOccurrence(f"no slot {slot_key!r} on {day} for habit {habit_key!r}")


def record(
    occurrence: Occurrence,
    *,
    occurred_at: datetime | None = None,
    component=None,
    project=None,
    value=None,
    unit: str = "",
    duration_seconds: int | None = None,
    note: str = "",
    entry_mode: str = EntryMode.LIVE,
    client_ts: datetime | None = None,
    settings: AppSettings | None = None,
    now: datetime | None = None,
) -> HabitLog:
    settings = settings or AppSettings.get()
    now = now or timezone.now()

    # Validate against when the DEVICE created it, not when the server received
    # it: a backfill made on day 7 that syncs on day 9 was legitimate when made.
    reference = (client_ts or now).date()
    floor = reference - timedelta(days=settings.backfill_days)
    if occurrence.habit_day < floor:
        raise BackfillTooOld(
            f"habit_day {occurrence.habit_day} is older than the "
            f"{settings.backfill_days}-day backfill window"
        )

    status = classify(occurrence, occurred_at)
    habit = Habit.objects.get(key=occurrence.habit_key)

    if habit.requires_project and project is None:
        raise ValidationError(f"habit {habit.key!r} requires a project")

    return HabitLog.objects.create(
        habit=habit,
        slot_key=occurrence.slot_key,
        # From the occurrence, never derived independently from wall time. That
        # is what stops a prayer near the rollover landing on the wrong day.
        habit_day=occurrence.habit_day,
        occurred_at=occurred_at or occurrence.window_start or occurrence.day_start,
        component=component,
        project=project,
        value=value,
        unit=unit or occurrence.target_unit,
        duration_seconds=duration_seconds,
        note=note,
        status=status,
        window_start_at=occurrence.window_start,
        window_end_at=occurrence.window_end,
        schedule_version_id=occurrence.schedule_version_id,
        location_id=occurrence.location_id,
        entry_mode=entry_mode,
        client_ts=client_ts,
    )
