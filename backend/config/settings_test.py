"""Test settings: production settings plus the sync-primitive fixture app.

Kept separate so `apps.synctest` never reaches a real database and never shows
up in `makemigrations --check` against config.settings.
"""

from .settings import *  # noqa: F403
from .settings import INSTALLED_APPS

INSTALLED_APPS = [*INSTALLED_APPS, "apps.synctest"]
