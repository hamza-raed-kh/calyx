from django.apps import AppConfig


class SyncTestConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.synctest"

    def ready(self) -> None:
        from apps.sync.registry import registry

        from .models import Gadget, Widget
        from .serializers import GadgetSerializer, WidgetSerializer

        registry.register("widgets", Widget, WidgetSerializer)
        registry.register("gadgets", Gadget, GadgetSerializer)
