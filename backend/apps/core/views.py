from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Liveness + database reachability.

    Unauthenticated on purpose: `ops/deploy.sh` polls this after every deploy,
    before any token exists.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # report, never raise, from a health check
        return Response({"status": "degraded", "database": "unreachable", "detail": str(exc)}, 503)
    return Response({"status": "ok", "database": "ok"})
