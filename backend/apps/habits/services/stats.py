"""Completion statistics.

No streaks anywhere -- not in the schema, not in the API, not in the payload.
Rates over a trailing window plus a per-slot breakdown, which is what actually
answers "which prayer do I keep missing" without the all-or-nothing framing a
streak imposes.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from ..enums import Frequency, LogStatus, Requirement
from ..models import Habit, HabitLog
from .occurrences import Occurrence, OccurrenceGenerator


def satisfied(occurrence: Occurrence, logs: list[HabitLog]) -> bool:
    """Whether one slot-day is done.

    SUM, not max, is why "10 pages this morning, 10 more tonight" works.
    len(logs) > 0 is why "at least one gaming session" works. One rule, no
    special cases.
    """
    live = [log for log in logs if log.deleted_at is None]
    if occurrence.target_value is None:
        return bool(live)
    total = sum((log.value or Decimal(0)) for log in live)
    return total >= occurrence.target_value


@dataclass
class SlotBreakdown:
    key: str
    label: str
    expected: int = 0
    satisfied: int = 0
    on_time: int = 0
    late: int = 0

    @property
    def missed(self) -> int:
        return self.expected - self.satisfied

    @property
    def rate(self) -> float | None:
        return round(self.satisfied / self.expected, 4) if self.expected else None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "expected": self.expected,
            "satisfied": self.satisfied,
            "missed": self.missed,
            "on_time": self.on_time,
            "late": self.late,
            "rate": self.rate,
        }


@dataclass
class PeriodBreakdown:
    key: str
    target: int
    sessions: int = 0

    @property
    def counted(self) -> int:
        """Sessions capped at the target.

        Capping per week is essential: without it a six-session week papers over
        a zero-session week and the rate becomes meaningless.
        """
        return min(self.sessions, self.target)

    @property
    def met(self) -> bool:
        return self.sessions >= self.target


@dataclass
class HabitStats:
    habit_key: str
    habit_name: str
    frequency: str
    window_start: date_cls | None = None
    window_end: date_cls | None = None
    eligible_days: int = 0
    expected_slots: int = 0
    satisfied_slots: int = 0
    perfect_days: int = 0
    unavailable_slots: int = 0
    on_time: int = 0
    late: int = 0
    unknown: int = 0
    by_slot: list[SlotBreakdown] = field(default_factory=list)
    component_mix: dict[str, int] = field(default_factory=dict)
    periods: list[PeriodBreakdown] = field(default_factory=list)
    current_period: dict | None = None

    @property
    def slot_rate(self) -> float | None:
        """The headline. Partial, not binary: 4 of 5 prayers is not 0 of 5."""
        return round(self.satisfied_slots / self.expected_slots, 4) if self.expected_slots else None

    @property
    def perfect_day_rate(self) -> float | None:
        return round(self.perfect_days / self.eligible_days, 4) if self.eligible_days else None

    @property
    def punctuality_rate(self) -> float | None:
        """Computed only over logs that exist, and excluding UNKNOWN.

        A backfill with no recorded time counts fully toward completion but must
        not be scored as either punctual or late -- otherwise filling in
        yesterday either flatters or punishes you for no reason.
        """
        judged = self.on_time + self.late
        return round(self.on_time / judged, 4) if judged else None

    @property
    def period_rate(self) -> float | None:
        if not self.periods:
            return None
        counted = sum(period.counted for period in self.periods)
        target = sum(period.target for period in self.periods)
        return round(counted / target, 4) if target else None

    def as_dict(self) -> dict:
        payload = {
            "habit_key": self.habit_key,
            "habit_name": self.habit_name,
            "frequency": self.frequency,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "eligible_days": self.eligible_days,
            "expected_slots": self.expected_slots,
            "satisfied_slots": self.satisfied_slots,
            "unavailable_slots": self.unavailable_slots,
            "slot_rate": self.slot_rate,
            "perfect_day_rate": self.perfect_day_rate,
            "punctuality": {
                "on_time": self.on_time,
                "late": self.late,
                "unknown": self.unknown,
                "rate": self.punctuality_rate,
            },
            "by_slot": [slot.as_dict() for slot in self.by_slot],
            "component_mix": self.component_mix,
        }
        if self.frequency == Frequency.TIMES_PER_WEEK:
            payload["periods"] = [
                {"key": p.key, "target": p.target, "sessions": p.sessions, "met": p.met}
                for p in self.periods
            ]
            payload["periods_met"] = sum(1 for p in self.periods if p.met)
            payload["period_rate"] = self.period_rate
            payload["current_period"] = self.current_period
        return payload


class StatsCalculator:
    def __init__(self, generator: OccurrenceGenerator | None = None, now: datetime | None = None):
        self.generator = generator or OccurrenceGenerator()
        self.now = now or timezone.now()

    def for_habit(self, habit: Habit, *, days: int) -> HabitStats:
        today = self.now.astimezone(self.generator.tz_for(self.now.date())).date()
        start = today - timedelta(days=days)

        self.generator.preload_prayer_times(start, today)
        occurrences = self.generator.generate(habit, start, today)

        stats = HabitStats(
            habit_key=habit.key,
            habit_name=habit.name,
            frequency=_frequency_of(habit, occurrences),
        )
        if not occurrences:
            return stats

        logs = _logs_by_slot_day(habit, start, today)

        if stats.frequency == Frequency.TIMES_PER_WEEK:
            self._weekly(stats, occurrences, logs)
        else:
            self._daily(stats, occurrences, logs)
        return stats

    # --- daily --------------------------------------------------------------

    def _daily(self, stats, occurrences, logs) -> None:
        # Only fully elapsed days count. Including today would crater every rate
        # each morning and heal it each evening -- noise, not information.
        elapsed = [o for o in occurrences if o.day_end <= self.now]
        if not elapsed:
            return

        stats.window_start = min(o.habit_day for o in elapsed)
        stats.window_end = max(o.habit_day for o in elapsed)

        by_key: dict[str, SlotBreakdown] = {}
        per_day: dict[date_cls, list[bool]] = defaultdict(list)

        for occurrence in elapsed:
            if occurrence.requirement == Requirement.UNAVAILABLE:
                # High latitude: neither numerator nor denominator. Never a miss.
                stats.unavailable_slots += 1
                continue

            breakdown = by_key.setdefault(
                occurrence.slot_key, SlotBreakdown(occurrence.slot_key, occurrence.slot_label)
            )
            breakdown.expected += 1
            stats.expected_slots += 1

            entries = logs.get((occurrence.slot_key, occurrence.habit_day), [])
            done = satisfied(occurrence, entries)
            per_day[occurrence.habit_day].append(done)
            if done:
                breakdown.satisfied += 1
                stats.satisfied_slots += 1

            for entry in entries:
                if entry.status == LogStatus.ON_TIME:
                    breakdown.on_time += 1
                    stats.on_time += 1
                elif entry.status == LogStatus.LATE:
                    breakdown.late += 1
                    stats.late += 1
                else:
                    stats.unknown += 1
                if entry.component_id:
                    key = entry.component.key
                    stats.component_mix[key] = stats.component_mix.get(key, 0) + 1

        stats.eligible_days = len(per_day)
        stats.perfect_days = sum(1 for results in per_day.values() if results and all(results))
        stats.by_slot = sorted(by_key.values(), key=lambda item: item.key)

    # --- times per week -----------------------------------------------------

    def _weekly(self, stats, occurrences, logs) -> None:
        by_period: dict[str, list[Occurrence]] = defaultdict(list)
        for occurrence in occurrences:
            by_period[occurrence.period_key].append(occurrence)

        current_key = max(by_period) if by_period else None

        for key in sorted(by_period):
            group = by_period[key]
            sessions = sum(
                len(
                    [
                        log
                        for log in logs.get((o.slot_key, o.habit_day), [])
                        if log.deleted_at is None
                    ]
                )
                for o in group
            )
            target = group[0].period_target or 1

            # A week still running, or one clipped by the window edge, is not a
            # week you failed. Prorating is wrong for this shape: three sessions
            # on Fri/Sat/Sun is a perfectly good week that proration marks as
            # failing on Monday.
            complete = len(group) == 7 and all(o.day_end <= self.now for o in group)
            if not complete:
                if key == current_key:
                    days_left = sum(1 for o in group if o.day_end > self.now)
                    stats.current_period = {
                        "key": key,
                        "target": target,
                        "sessions": sessions,
                        "remaining": max(target - sessions, 0),
                        "days_left": days_left,
                    }
                continue

            stats.periods.append(PeriodBreakdown(key=key, target=target, sessions=sessions))
            stats.eligible_days += 7
            stats.expected_slots += target
            stats.satisfied_slots += min(sessions, target)

            for occurrence in group:
                for entry in logs.get((occurrence.slot_key, occurrence.habit_day), []):
                    if entry.status == LogStatus.ON_TIME:
                        stats.on_time += 1
                    elif entry.status == LogStatus.LATE:
                        stats.late += 1
                    else:
                        stats.unknown += 1

        if stats.periods:
            first = stats.periods[0].key.split("/")[0]
            last = stats.periods[-1].key.split("/")[0]
            stats.window_start = date_cls.fromisoformat(first)
            stats.window_end = date_cls.fromisoformat(last) + timedelta(days=6)


def heatmap(habits, start: date_cls, end: date_cls, *, now: datetime | None = None) -> list[dict]:
    """Per-day completion fraction across all habits, for a calendar heatmap."""
    generator = OccurrenceGenerator()
    generator.preload_prayer_times(start, end)
    now = now or timezone.now()

    totals: dict[date_cls, list[int]] = defaultdict(lambda: [0, 0])
    for habit in habits:
        occurrences = generator.generate(habit, start, end)
        logs = _logs_by_slot_day(habit, start, end)
        for occurrence in occurrences:
            if occurrence.requirement == Requirement.UNAVAILABLE or occurrence.day_end > now:
                continue
            bucket = totals[occurrence.habit_day]
            bucket[0] += 1
            if satisfied(occurrence, logs.get((occurrence.slot_key, occurrence.habit_day), [])):
                bucket[1] += 1

    return [
        {
            "habit_day": day.isoformat(),
            "expected": expected,
            "satisfied": done,
            "fraction": round(done / expected, 4) if expected else None,
        }
        for day, (expected, done) in sorted(totals.items())
    ]


def _logs_by_slot_day(habit, start, end) -> dict[tuple[str, date_cls], list[HabitLog]]:
    grouped: dict[tuple[str, date_cls], list[HabitLog]] = defaultdict(list)
    query = (
        HabitLog.objects.live()
        .filter(habit=habit, habit_day__gte=start, habit_day__lte=end)
        .select_related("component")
    )
    for log in query:
        grouped[(log.slot_key, log.habit_day)].append(log)
    return grouped


def _frequency_of(habit, occurrences) -> str:
    if occurrences and occurrences[0].period_target is not None:
        return Frequency.TIMES_PER_WEEK
    return Frequency.DAILY
