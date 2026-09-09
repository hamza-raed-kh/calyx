from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.tasks import services
from apps.tasks.models import Project, Task

pytestmark = pytest.mark.django_db


def at(year, month, day, hour=9):
    return datetime(year, month, day, hour, tzinfo=UTC)


def test_completing_a_one_off_spawns_nothing():
    task = Task.objects.create(title="once")
    assert services.complete(task) is None
    assert Task.objects.count() == 1


def test_completing_a_recurring_task_spawns_the_next_instance():
    task = Task.objects.create(title="rent", due_at=at(2026, 9, 1), recurrence="FREQ=MONTHLY")

    following = services.complete(task)

    assert following is not None
    assert following.due_at == at(2026, 10, 1)
    assert following.completed_at is None
    assert following.recurrence == "FREQ=MONTHLY"


def test_the_spawned_instance_points_back_at_the_series_root():
    task = Task.objects.create(title="rent", due_at=at(2026, 9, 1), recurrence="FREQ=MONTHLY")
    second = services.complete(task)
    third = services.complete(second)

    assert second.recurrence_parent_id == task.id
    # The chain must not deepen: every instance points at the root, not at its
    # immediate predecessor, or the ancestry grows without bound.
    assert third.recurrence_parent_id == task.id


def test_completing_twice_does_not_spawn_twice():
    """Completion is a set-value, so a retried mutation must be a no-op."""
    task = Task.objects.create(title="rent", due_at=at(2026, 9, 1), recurrence="FREQ=MONTHLY")

    first = services.complete(task)
    second = services.complete(task)

    assert first is not None
    assert second is None
    assert Task.objects.count() == 2


def test_weekly_byday_advances_to_the_next_listed_day():
    # 2026-09-09 is a Wednesday.
    task = Task.objects.create(
        title="standup", due_at=at(2026, 9, 9), recurrence="FREQ=WEEKLY;BYDAY=MO,WE"
    )
    following = services.complete(task)
    assert following.due_at == at(2026, 9, 14)  # Monday


def test_a_bounded_series_ends_rather_than_spawning_forever():
    task = Task.objects.create(
        title="thrice", due_at=at(2026, 9, 1), recurrence="FREQ=DAILY;COUNT=2"
    )
    second = services.complete(task)
    assert second is not None
    assert services.complete(second) is None


def test_invalid_recurrence_is_reported_not_swallowed():
    task = Task.objects.create(title="bad", due_at=at(2026, 9, 1), recurrence="FREQ=NONSENSE")
    with pytest.raises(services.InvalidRecurrence):
        services.next_due(task)


def test_reopen_clears_completion():
    task = Task.objects.create(title="x")
    services.complete(task)
    services.reopen(task)
    assert task.completed_at is None


def test_overdue_excludes_completed_and_tombstoned():
    past = timezone.now() - timedelta(days=1)
    live = Task.objects.create(title="late", due_at=past)
    done = Task.objects.create(title="done", due_at=past, completed_at=timezone.now())
    gone = Task.objects.create(title="gone", due_at=past)
    gone.soft_delete()

    assert {t.id for t in services.overdue()} == {live.id}
    assert done.id not in {t.id for t in services.overdue()}


def test_subtasks_and_project_link():
    project = Project.objects.create(name="Umbra")
    parent = Task.objects.create(title="parent", project=project)
    child = Task.objects.create(title="child", parent=parent, project=project)

    assert list(parent.subtasks.all()) == [child]
    assert list(project.tasks.order_by("title")) == [child, parent]


def test_tag_ids_survive_a_round_trip():
    tag_id = "018f0000-0000-7000-8000-00000000abcd"
    task = Task.objects.create(title="tagged", tag_ids=[tag_id])
    task.refresh_from_db()
    assert [str(t) for t in task.tag_ids] == [tag_id]
