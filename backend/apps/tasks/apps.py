from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"

    def ready(self) -> None:
        from apps.sync.registry import registry

        from .models import Project, Tag, Task
        from .serializers import ProjectSerializer, TagSerializer, TaskSerializer

        registry.register("projects", Project, ProjectSerializer)
        registry.register("tags", Tag, TagSerializer)
        registry.register("tasks", Task, TaskSerializer)
