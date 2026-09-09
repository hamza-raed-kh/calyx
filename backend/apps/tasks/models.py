"""Tasks: projects, tasks, subtasks, tags, and their own recurrence engine.

Deliberately separate from habits. The two overlap conceptually, but prayers
with astronomically computed windows and "buy milk weekly" want very different
schemas, and sharing one would make both uglier.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import SyncableModel


class Priority(models.IntegerChoices):
    NONE = 0, "None"
    LOW = 1, "Low"
    MEDIUM = 2, "Medium"
    HIGH = 3, "High"


class Project(SyncableModel):
    """A body of work. Also the target of the work-session habit."""

    name = models.CharField(max_length=120)
    color = models.CharField(max_length=9, blank=True)
    icon = models.CharField(max_length=32, blank=True)
    notes = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Tag(SyncableModel):
    name = models.CharField(max_length=60)
    color = models.CharField(max_length=9, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Task(SyncableModel):
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="subtasks"
    )

    title = models.CharField(max_length=300)
    notes = models.TextField(blank=True)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.NONE)

    # Tag membership as an array rather than a join table: a join table has no
    # row_version of its own, so it cannot take part in a cursor-ordered sync.
    # An array rides along atomically with the task. A tag that is later deleted
    # leaves an id pointing at a tombstone, which the UI simply hides.
    tag_ids = ArrayField(models.UUIDField(), default=list, blank=True)

    # When it is *due* versus when you intend to *do* it. Keeping both is the
    # difference between "overdue" and "not today".
    due_at = models.DateTimeField(null=True, blank=True)
    due_is_all_day = models.BooleanField(default=True)
    scheduled_for = models.DateField(null=True, blank=True)

    # A set-value, never a toggle: a retried toggle undoes itself, a retried
    # set-value is a no-op. That is what makes offline replay safe.
    completed_at = models.DateTimeField(null=True, blank=True)

    # RFC 5545 RRULE subset, e.g. "FREQ=WEEKLY;BYDAY=MO,WE". Empty means one-off.
    recurrence = models.CharField(max_length=200, blank=True)
    #: Set on an instance spawned by completing a recurring task.
    recurrence_parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="recurrence_children"
    )

    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "-priority", "due_at"]
        indexes = [
            models.Index(fields=["completed_at"]),
            models.Index(fields=["due_at"]),
            models.Index(fields=["scheduled_for"]),
        ]
        constraints = [
            # One level of nesting. Arbitrary depth turns every list render into
            # a recursive query for no benefit anyone asked for.
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")),
                name="task_is_not_its_own_parent",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None
