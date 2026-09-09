"""Habit endpoints: the agenda, logging, and statistics."""

from datetime import date as date_cls
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .enums import EntryMode, Requirement
from .models import AppSettings, Habit, HabitComponent, HabitLog
from .serializers import HabitLogSerializer
from .services import logging as log_service
from .services.occurrences import OccurrenceGenerator
from .services.stats import StatsCalculator, heatmap, satisfied

DEFAULT_WINDOWS = (7, 30, 90)


@api_view(["GET"])
def agenda(request):
    """Everything expected of you on one habit-day, plus what is still open from
    the previous one.

    Carryover is not a rounding error: Isha's window legitimately runs past the
    03:00 rollover, so at 03:30 a still-open Isha belongs to yesterday.
    """
    settings = AppSettings.get()
    generator = OccurrenceGenerator(settings)
    now = timezone.now()
    day = _parse_date(request.query_params.get("date"), generator, now)
    return Response(_agenda_for(day, generator, settings, now))


@api_view(["GET"])
def horizon(request):
    """Expanded occurrences for a run of days, for the client to cache.

    The device never reimplements the generator: DST resolution, rollover
    assignment, prayer-window chaining and high-latitude fallback exist once, on
    the server, and the wire format is literally that function's output. A
    second implementation in Dart would eventually disagree by a minute, and the
    same log would read on-time on the phone and late on the server.
    """
    settings = AppSettings.get()
    generator = OccurrenceGenerator(settings)
    now = timezone.now()

    start = _parse_date(request.query_params.get("from"), generator, now)
    days = _parse_horizon(request.query_params.get("days"), settings)
    end = start + timedelta(days=days - 1)

    generator.preload_prayer_times(start - timedelta(days=1), end)
    return Response(
        {
            "from": start,
            "to": end,
            "server_time": now,
            "days": [
                _agenda_for(start + timedelta(days=offset), generator, settings, now)
                for offset in range(days)
            ],
        }
    )


def _agenda_for(day, generator, settings, now) -> dict:
    previous = day - timedelta(days=1)
    generator.preload_prayer_times(previous, day)
    habits = list(Habit.objects.live().prefetch_related("versions__slots", "components"))

    occurrences = []
    for habit in habits:
        occurrences.extend(generator.generate(habit, previous, day))

    logs = _logs_for(previous, day)
    by_habit = {str(habit.id): habit for habit in habits}

    today_rows, carryover_rows, flexible_rows = [], [], []
    for occurrence in occurrences:
        habit = by_habit.get(occurrence.habit_id)
        if habit is None:
            continue
        entries = logs.get((occurrence.habit_key, occurrence.slot_key, occurrence.habit_day), [])
        payload = _occurrence_payload(occurrence, habit, entries, now)

        if occurrence.requirement == Requirement.TOWARD_PERIOD:
            if occurrence.habit_day == day:
                flexible_rows.append(payload)
            continue

        if occurrence.habit_day == day:
            today_rows.append(payload)
        elif payload["state"] == "open":
            carryover_rows.append(payload)

    day_start = min((o.day_start for o in occurrences if o.habit_day == day), default=None)
    day_end = max((o.day_end for o in occurrences if o.habit_day == day), default=None)

    expected = [row for row in today_rows if row["requirement"] == Requirement.REQUIRED]
    satisfied_count = sum(1 for row in expected if row["progress"]["satisfied"])

    return {
            "habit_day": day,
            "day_start": day_start,
            "day_end": day_end,
            "server_time": now,
            "timezone": str(generator.tz_for(day)),
            "backfill_floor": day - timedelta(days=settings.backfill_days),
            "occurrences": sorted(today_rows, key=_sort_key),
            "carryover": sorted(carryover_rows, key=_sort_key),
            "flexible": flexible_rows,
            "summary": {
                "expected_slots": len(expected),
                "satisfied_slots": satisfied_count,
                "perfect": bool(expected) and satisfied_count == len(expected),
            },
        }


@api_view(["POST"])
def create_log(request):
    """Record a log against an occurrence.

    The client sends an id it derived locally; the server re-derives the
    occurrence from the schedule valid on that day rather than trusting it, so a
    stale or hand-made id cannot invent a window to be judged against.
    """
    data = request.data
    occurrence_id = data.get("occurrence_id")
    if not occurrence_id:
        raise ValidationError({"occurrence_id": "required"})

    # Idempotency. An offline log is queued with a client-generated id and may
    # be delivered more than once -- a retry after a response was lost, say.
    # Returning the existing row makes that free, and is why habit logging can
    # be queued at all rather than needing an online round trip.
    supplied_id = data.get("id")
    if supplied_id:
        existing = HabitLog.objects.filter(pk=supplied_id).first()
        if existing is not None:
            return Response(HabitLogSerializer(existing).data, status=200)

    try:
        occurrence = log_service.resolve(occurrence_id)
    except log_service.UnknownOccurrence as exc:
        raise ValidationError({"occurrence_id": str(exc)}) from exc

    component = None
    if data.get("component"):
        component = HabitComponent.objects.filter(
            habit__key=occurrence.habit_key, key=data["component"]
        ).first()
        if component is None:
            raise ValidationError({"component": f"unknown component {data['component']!r}"})

    try:
        entry = log_service.record(
            occurrence,
            occurred_at=_parse_dt(data.get("occurred_at")),
            component=component,
            project_id=data.get("project"),
            value=data.get("value"),
            unit=data.get("unit", ""),
            duration_seconds=data.get("duration_seconds"),
            note=data.get("note", ""),
            entry_mode=data.get("entry_mode", EntryMode.LIVE),
            client_ts=_parse_dt(data.get("client_ts")),
            log_id=supplied_id or None,
        )
    except DjangoValidationError as exc:
        raise ValidationError({"detail": exc.messages}) from exc

    return Response(HabitLogSerializer(entry).data, status=201)


@api_view(["GET"])
def rates(request):
    windows = _parse_windows(request.query_params.get("windows"))
    calculator = StatsCalculator()

    payload = []
    for habit in Habit.objects.live():
        entry = {"habit_key": habit.key, "habit_name": habit.name, "windows": {}}
        for days in windows:
            entry["windows"][str(days)] = calculator.for_habit(habit, days=days).as_dict()
        payload.append(entry)

    return Response({"habits": payload, "server_time": timezone.now()})


@api_view(["GET"])
def heatmap_view(request):
    generator = OccurrenceGenerator()
    now = timezone.now()
    today = now.astimezone(generator.tz_for(now.date())).date()

    end = _parse_date_param(request.query_params.get("to"), today)
    start = _parse_date_param(request.query_params.get("from"), end - timedelta(days=180))
    if start > end:
        raise ValidationError({"from": "must not be after 'to'"})

    return Response({"cells": heatmap(Habit.objects.live(), start, end, now=now)})


# --- helpers -----------------------------------------------------------------


def _occurrence_payload(occurrence, habit, entries, now) -> dict:
    live = [entry for entry in entries if entry.deleted_at is None]
    total = sum((entry.value or 0) for entry in live) if occurrence.target_value else None

    return {
        "id": occurrence.id,
        "habit": {
            "id": str(habit.id),
            "key": habit.key,
            "name": habit.name,
            "icon": habit.icon,
            "color": habit.color,
            "component_mode": habit.component_mode,
            "requires_project": habit.requires_project,
            "allows_project": habit.allows_project,
        },
        "slot": {"key": occurrence.slot_key, "label": occurrence.slot_label},
        "habit_day": occurrence.habit_day,
        "window_start": occurrence.window_start,
        "window_end": occurrence.window_end,
        "day_start": occurrence.day_start,
        "day_end": occurrence.day_end,
        "state": occurrence.state(now),
        "requirement": occurrence.requirement,
        "target": (
            {"value": str(occurrence.target_value), "unit": occurrence.target_unit}
            if occurrence.target_value is not None
            else None
        ),
        "progress": {
            "satisfied": satisfied(occurrence, live),
            "value": str(total) if total is not None else None,
            "log_count": len(live),
        },
        "components": [
            {"key": component.key, "label": component.label, "is_active": component.is_active}
            for component in habit.components.all()
            if component.deleted_at is None
        ],
        "logs": [HabitLogSerializer(entry).data for entry in live],
        "notify_at": occurrence.notify_at,
        "remind_at": occurrence.remind_at,
        "period_key": occurrence.period_key,
        "period_target": occurrence.period_target,
    }


def _logs_for(start: date_cls, end: date_cls):
    grouped: dict[tuple[str, str, date_cls], list[HabitLog]] = {}
    query = (
        HabitLog.objects.live()
        .filter(habit_day__gte=start, habit_day__lte=end)
        .select_related("habit", "component")
    )
    for entry in query:
        grouped.setdefault((entry.habit.key, entry.slot_key, entry.habit_day), []).append(entry)
    return grouped


def _sort_key(row) -> tuple:
    return (row["window_start"] is None, row["window_start"] or datetime.min, row["slot"]["key"])


def _parse_date(value, generator, now) -> date_cls:
    today = now.astimezone(generator.tz_for(now.date())).date()
    if value in (None, "", "today"):
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    return _parse_date_param(value, today)


def _parse_date_param(value, fallback: date_cls) -> date_cls:
    if not value:
        return fallback
    try:
        return date_cls.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({"date": f"expected YYYY-MM-DD, got {value!r}"}) from exc


def _parse_dt(value):
    if not value:
        return None
    parsed = timezone.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else timezone.make_aware(parsed)


def _parse_horizon(value, settings) -> int:
    if not value:
        return settings.prefetch_horizon_days
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"days": "must be an integer"}) from exc
    if not 1 <= days <= 120:
        raise ValidationError({"days": "must be between 1 and 120"})
    return days


def _parse_windows(value) -> tuple[int, ...]:
    if not value:
        return DEFAULT_WINDOWS
    try:
        windows = tuple(int(part) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise ValidationError({"windows": "expected a comma-separated list of integers"}) from exc
    if not windows or any(days < 0 or days > 1825 for days in windows):
        raise ValidationError({"windows": "each window must be between 0 and 1825 days"})
    return windows
