import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token

pytestmark = pytest.mark.django_db
User = get_user_model()

GOOD_PASSWORD = "correct-horse-battery-staple"


def register(anon, **payload):
    return anon.post(reverse("core:auth-register"), payload, format="json")


def login(anon, **payload):
    return anon.post(reverse("core:auth-login"), payload, format="json")


# --- claiming a fresh instance ----------------------------------------------


def test_a_fresh_instance_reports_itself_unclaimed(anon):
    body = anon.get(reverse("core:auth-config")).json()
    assert body["is_unclaimed"] is True
    assert body["registration_open"] is True


def test_the_first_account_can_be_created_without_ssh(anon, settings):
    """The whole point: claiming a deployment must not require a shell on it."""
    settings.ALLOW_SIGNUPS = False

    response = register(anon, username="omar", password=GOOD_PASSWORD)

    assert response.status_code == 201
    assert response.json()["token"]
    assert User.objects.count() == 1


def test_the_first_account_gets_the_admin(anon):
    register(anon, username="omar", password=GOOD_PASSWORD)
    user = User.objects.get(username="omar")
    assert user.is_staff and user.is_superuser


def test_the_instance_closes_behind_the_first_account(anon, settings):
    settings.ALLOW_SIGNUPS = False
    register(anon, username="omar", password=GOOD_PASSWORD)

    assert anon.get(reverse("core:auth-config")).json()["registration_open"] is False
    second = register(anon, username="someone", password=GOOD_PASSWORD)
    assert second.status_code == 400


def test_signups_flag_reopens_registration(anon, settings):
    settings.ALLOW_SIGNUPS = True
    register(anon, username="omar", password=GOOD_PASSWORD)

    assert register(anon, username="guest", password=GOOD_PASSWORD).status_code == 201


# --- registration validation -------------------------------------------------


def test_a_weak_password_is_refused_with_a_reason(anon):
    response = register(anon, username="omar", password="123")
    assert response.status_code == 400
    assert "password" in response.json()


def test_a_taken_username_is_refused_case_insensitively(anon, settings):
    settings.ALLOW_SIGNUPS = True
    register(anon, username="omar", password=GOOD_PASSWORD)

    response = register(anon, username="OMAR", password=GOOD_PASSWORD)
    assert response.status_code == 400
    assert "username" in response.json()


# --- login -------------------------------------------------------------------


def test_login_returns_a_usable_token(anon):
    register(anon, username="omar", password=GOOD_PASSWORD)
    body = login(anon, username="omar", password=GOOD_PASSWORD).json()

    assert body["user"]["username"] == "omar"
    anon.credentials(HTTP_AUTHORIZATION=f"Token {body['token']}")
    assert anon.get(reverse("core:auth-me")).status_code == 200


def test_login_is_idempotent_rather_than_minting_tokens_forever(anon):
    register(anon, username="omar", password=GOOD_PASSWORD)
    first = login(anon, username="omar", password=GOOD_PASSWORD).json()["token"]
    second = login(anon, username="omar", password=GOOD_PASSWORD).json()["token"]
    assert first == second


@pytest.mark.parametrize(
    ("username", "password"),
    [("omar", "wrong-password-entirely"), ("nobody", GOOD_PASSWORD)],
)
def test_bad_credentials_are_refused(anon, username, password):
    register(anon, username="omar", password=GOOD_PASSWORD)
    assert login(anon, username=username, password=password).status_code == 400


def test_the_failure_message_does_not_say_which_half_was_wrong(anon):
    """Distinguishing them tells an attacker which usernames exist."""
    register(anon, username="omar", password=GOOD_PASSWORD)

    wrong_password = login(anon, username="omar", password="not-the-password").json()
    wrong_user = login(anon, username="ghost", password=GOOD_PASSWORD).json()

    assert wrong_password["detail"] == wrong_user["detail"]


def test_missing_credentials_are_rejected(anon):
    assert login(anon, username="", password="").status_code == 400


# --- session lifecycle -------------------------------------------------------


def test_me_requires_authentication(anon):
    assert anon.get(reverse("core:auth-me")).status_code in (401, 403)


def test_logout_revokes_the_token_server_side(anon):
    """Forgetting a token locally leaves a working credential on a lost device.

    Uses a real Authorization header rather than the force_authenticate fixture,
    which bypasses token auth and so could never observe a revoked token.
    """
    token = register(anon, username="omar", password=GOOD_PASSWORD).json()["token"]
    anon.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    assert anon.get(reverse("core:auth-me")).status_code == 200
    assert anon.post(reverse("core:auth-logout")).status_code == 204
    assert not Token.objects.filter(key=token).exists()
    assert anon.get(reverse("core:auth-me")).status_code in (401, 403)
