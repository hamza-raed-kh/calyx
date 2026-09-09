"""Account endpoints.

The app is single-user, but "single user" is not the same as "no accounts". A
self-hosted deployment still needs a way to claim itself and to prove who is
calling, and making the owner SSH in to mint a token by hand is internal
plumbing leaking into the product.

Bootstrap rule: while the instance has NO users, registration is open
regardless of ALLOW_SIGNUPS. That is what lets a fresh deployment be claimed
from the app itself. Once an account exists the flag governs, so the instance
closes behind the first person through the door.

The window is real but small: someone who reaches a brand-new deployment before
its owner could claim it. On a tailnet with nothing published that is close to
theoretical, and it is the trade every self-hosted app of this shape makes. Set
ALLOW_SIGNUPS=false and register immediately after deploying.
"""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

User = get_user_model()


def _user_payload(user) -> dict:
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": user.email,
        "is_staff": user.is_staff,
    }


def _registration_open() -> bool:
    return settings.ALLOW_SIGNUPS or not User.objects.exists()


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_config(request):
    """What the sign-in screen needs before anyone has authenticated.

    Deliberately does not leak how many users exist -- only whether this
    instance will currently accept a new one.
    """
    return Response(
        {
            "registration_open": _registration_open(),
            "is_unclaimed": not User.objects.exists(),
        }
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    if not username or not password:
        raise ValidationError({"detail": "Username and password are required."})

    user = authenticate(request, username=username, password=password)
    if user is None:
        # One message for both wrong-user and wrong-password: distinguishing
        # them tells an attacker which half they got right.
        raise ValidationError({"detail": "Incorrect username or password."})

    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": _user_payload(user)})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def register(request):
    if not _registration_open():
        raise ValidationError({"detail": "This instance is not accepting new accounts."})

    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    email = (request.data.get("email") or "").strip()

    if not username:
        raise ValidationError({"username": "Required."})
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError({"username": "That username is taken."})

    try:
        validate_password(password)
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from exc

    # The account that claims an unowned instance owns it: it gets the admin,
    # which is the escape hatch for everything the app does not expose.
    first = not User.objects.exists()
    user = User.objects.create_user(
        username=username, password=password, email=email, is_staff=first, is_superuser=first
    )
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": _user_payload(user)}, status=201)


@api_view(["GET"])
def me(request):
    return Response(_user_payload(request.user))


@api_view(["POST"])
def logout(request):
    """Invalidate this token.

    Sign-out has to revoke server-side, not merely forget locally: a token
    dropped from a device that was lost is still a valid credential.
    """
    Token.objects.filter(user=request.user).delete()
    return Response(status=204)
