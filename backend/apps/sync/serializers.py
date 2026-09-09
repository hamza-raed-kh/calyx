from rest_framework import serializers


class SyncableSerializer(serializers.ModelSerializer):
    """Base for every synced entity.

    ``row_version`` and ``updated_at`` are written by a database trigger, so
    they are read-only here: accepting them from a client would let a device
    with a wrong clock or a stale cache rewrite the ordering the whole sync
    protocol depends on.
    """

    class Meta:
        fields = ["id", "row_version", "created_at", "updated_at", "client_ts", "deleted_at"]
        read_only_fields = ["row_version", "updated_at", "client_ts"]


class MutationSerializer(serializers.Serializer):
    mutation_id = serializers.UUIDField()
    seq = serializers.IntegerField(min_value=0)
    entity = serializers.CharField(max_length=64)
    op = serializers.ChoiceField(choices=["upsert", "delete"])
    id = serializers.UUIDField()
    client_ts = serializers.DateTimeField(required=False, allow_null=True)
    base_row_version = serializers.IntegerField(required=False, allow_null=True)
    payload = serializers.DictField(required=False, default=dict)


class PushSerializer(serializers.Serializer):
    client_id = serializers.CharField(max_length=64)
    mutations = serializers.ListField(child=MutationSerializer(), allow_empty=True)
