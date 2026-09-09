"""Task recurrence.

Separate engine from habits, on purpose. A recurring task is a chain: completing
one instance spawns the next. A habit is a schedule that generates expectations
without any row existing until you log against it.
"""

from datetime import datetime, timedelta

from dateutil.rrule import rrulestr
from django.db import transaction
from django.utils import timezone

from .models import Task


class InvalidRecurrence(ValueError):
    pass


def parse_recurrence(rule: str, dtstart: datetime):
    """Validate and build an rrule. Raises InvalidRecurrence on anything unusable."""
    if not rule:
        raise InvalidRecurrence("empty recurrence")
    try:
        return rrulestr(rule, dtstart=dtstart)
    except Exception as exc:  # dateutil raises assorted types
        raise InvalidRecurrence(str(rule)) from exc


def next_due(task: Task, *, after: datetime | None = None) -> datetime | None:
    """The next due instant after `after`, or None if the series has ended."""
    if not task.recurrence:
        return None

    # Anchor at the SERIES ROOT, not this instance. Anchoring per-instance
    # restarts COUNT and UNTIL on every completion, so a bounded series would
    # spawn forever and never terminate.
    root = task.recurrence_parent or task
    anchor = root.due_at or root.created_at
    after = after or task.due_at or timezone.now()

    rule = parse_recurrence(task.recurrence, anchor)
    # rrule is inclusive of dtstart, so step past `after` explicitly rather than
    # handing back the instance that was just completed.
    return rule.after(after, inc=False)


@transaction.atomic
def complete(task: Task, *, when: datetime | None = None) -> Task | None:
    """Mark a task complete. Returns the spawned next instance, if any.

    Completion is a set-value, so calling this twice is not harmful -- but the
    second call must not spawn a second instance, which is why it short-circuits
    on an already-complete task.
    """
    if task.completed_at is not None:
        return None

    task.completed_at = when or timezone.now()
    task.save(update_fields=["completed_at"])

    if not task.recurrence:
        return None

    following = next_due(task, after=task.due_at or task.completed_at)
    if following is None:
        return None

    return Task.objects.create(
        project=task.project,
        parent=task.parent,
        title=task.title,
        notes=task.notes,
        priority=task.priority,
        tag_ids=list(task.tag_ids),
        due_at=following,
        due_is_all_day=task.due_is_all_day,
        scheduled_for=following.date() if task.scheduled_for else None,
        recurrence=task.recurrence,
        recurrence_parent=task.recurrence_parent or task,
        sort_order=task.sort_order,
    )


def reopen(task: Task) -> None:
    task.completed_at = None
    task.save(update_fields=["completed_at"])


def overdue(now: datetime | None = None):
    now = now or timezone.now()
    return Task.objects.live().filter(completed_at__isnull=True, due_at__lt=now)


def due_within(days: int, *, now: datetime | None = None):
    now = now or timezone.now()
    return Task.objects.live().filter(
        completed_at__isnull=True,
        due_at__gte=now,
        due_at__lt=now + timedelta(days=days),
    )
