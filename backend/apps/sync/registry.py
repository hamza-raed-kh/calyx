"""Which models participate in sync, and how they serialise.

Entities register themselves from their app's ``AppConfig.ready()``. The sync
endpoints know nothing about habits or tasks -- adding an entity is a
registration, not a change to pull/push.
"""

from dataclasses import dataclass

from apps.core.models import SyncableModel


@dataclass(frozen=True)
class SyncEntity:
    #: Wire name, e.g. "habit_logs". Stable forever: it appears in client
    #: mutations and in the pull payload, so renaming it breaks old outboxes.
    name: str
    model: type[SyncableModel]
    serializer: type


class SyncRegistry:
    def __init__(self) -> None:
        self._entities: dict[str, SyncEntity] = {}

    def register(self, name: str, model: type[SyncableModel], serializer: type) -> None:
        if name in self._entities and self._entities[name].model is not model:
            raise ValueError(f"sync entity {name!r} is already registered to a different model")
        if not issubclass(model, SyncableModel):
            raise TypeError(f"{model.__name__} is not a SyncableModel")
        self._entities[name] = SyncEntity(name=name, model=model, serializer=serializer)

    def get(self, name: str) -> SyncEntity | None:
        return self._entities.get(name)

    def all(self) -> list[SyncEntity]:
        # Sorted so the pull payload key order is stable, which makes responses
        # diffable in tests and in a proxy log.
        return [self._entities[name] for name in sorted(self._entities)]

    def clear(self) -> None:
        """Test hook only."""
        self._entities.clear()


registry = SyncRegistry()
