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


def test_secret_key_is_generated_and_persisted_when_unset(tmp_path, monkeypatch):
    """A compose file with no .env must not fall back to a published constant."""
    from importlib import reload

    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setenv("DJANGO_SECRET_KEY_FILE", str(tmp_path / "secret_key"))

    from config import settings

    first = settings._secret_key()
    second = settings._secret_key()

    assert len(first) > 40
    assert first == second, "the key must persist, or every restart logs you out"
    assert "insecure" not in first
    reload(settings)


def test_secret_key_falls_back_to_ephemeral_rather_than_a_known_value(monkeypatch):
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setenv("DJANGO_SECRET_KEY_FILE", "/proc/nonexistent/secret_key")

    from config import settings

    key = settings._secret_key()
    assert len(key) > 40
    assert key != settings._secret_key(), "an unwritable path must not reuse a fixed value"
