from apps.sync.serializers import SyncableSerializer

from .models import Project, Tag, Task


class ProjectSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = Project
        fields = [
            *SyncableSerializer.Meta.fields,
            "name",
            "color",
            "icon",
            "notes",
            "sort_order",
            "archived_at",
        ]


class TagSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = Tag
        fields = [*SyncableSerializer.Meta.fields, "name", "color"]


class TaskSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = Task
        fields = [
            *SyncableSerializer.Meta.fields,
            "project",
            "parent",
            "title",
            "notes",
            "priority",
            "tag_ids",
            "due_at",
            "due_is_all_day",
            "scheduled_for",
            "completed_at",
            "recurrence",
            "recurrence_parent",
            "sort_order",
        ]
