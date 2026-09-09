"""Throwaway models that exist only to exercise the sync primitives.

Installed by `config.settings_test` and nothing else, so these tables are never
created in a real database. Two models rather than one: the point of a single
shared sequence is that row_version orders changes *across* entity types, and
that cannot be tested with one table.
"""

from django.db import models

from apps.core.models import SyncableModel


class Widget(SyncableModel):
    name = models.CharField(max_length=50)


class Gadget(SyncableModel):
    name = models.CharField(max_length=50)
