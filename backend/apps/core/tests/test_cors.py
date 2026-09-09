"""CORS is only needed when the web client is served from a different origin
than the API. These tests pin the behaviour either way, because a wrong value
surfaces as an opaque browser error rather than anything in the server log."""

import pytest
from django.urls import reverse

WEB = "https://calyx.example.ts.net"
OTHER = "https://not-mine.example.com"


@pytest.mark.django_db
def test_no_cors_headers_when_no_origins_are_configured(client, settings):
    """Same-origin deployments must not advertise cross-origin access."""
    settings.CORS_ALLOWED_ORIGINS = []
    response = client.get(reverse("core:health"), headers={"origin": WEB})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


@pytest.mark.django_db
def test_a_configured_origin_is_allowed(client, settings):
    settings.CORS_ALLOWED_ORIGINS = [WEB]
    response = client.get(reverse("core:health"), headers={"origin": WEB})
    assert response.headers["Access-Control-Allow-Origin"] == WEB


@pytest.mark.django_db
def test_an_unconfigured_origin_is_refused(client, settings):
    settings.CORS_ALLOWED_ORIGINS = [WEB]
    response = client.get(reverse("core:health"), headers={"origin": OTHER})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


@pytest.mark.django_db
def test_preflight_permits_the_authorization_header(client, settings):
    """Token auth rides in Authorization; if the preflight omits it every
    authenticated call fails while the health check appears fine."""
    settings.CORS_ALLOWED_ORIGINS = [WEB]
    response = client.options(
        reverse("sync:pull"),
        headers={
            "origin": WEB,
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == WEB
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()


@pytest.mark.django_db
def test_credentials_are_not_advertised(client, settings):
    """Tokens travel in a header, not a cookie. Allowing credentials would add
    exposure for no benefit."""
    settings.CORS_ALLOWED_ORIGINS = [WEB]
    response = client.get(reverse("core:health"), headers={"origin": WEB})
    assert response.headers.get("Access-Control-Allow-Credentials") != "true"
