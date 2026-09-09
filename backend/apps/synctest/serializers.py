from apps.sync.serializers import SyncableSerializer

from .models import Gadget, Widget


class WidgetSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = Widget
        fields = [*SyncableSerializer.Meta.fields, "name"]


class GadgetSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = Gadget
        fields = [*SyncableSerializer.Meta.fields, "name"]
