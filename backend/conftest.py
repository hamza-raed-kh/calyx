import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api(db):
    """Authenticated API client. The app is single-user; there is exactly one."""
    user = get_user_model().objects.create_user(username="owner", password="x")
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anon():
    return APIClient()
