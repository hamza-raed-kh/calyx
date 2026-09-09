import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_reports_ok(client):
    response = client.get(reverse("core:health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_needs_no_authentication(client, settings):
    """deploy.sh polls this before any token exists, so it must stay open."""
    response = client.get(reverse("core:health"))
    assert response.status_code != 401
