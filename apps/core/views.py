from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness probe that also confirms the database answers."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            connection.cursor()
            database = "ok"
        except Exception as exc:  # noqa: BLE001 - surfaced as payload, not raised
            database = f"error: {exc}"
        return Response({"status": "ok", "database": database})
