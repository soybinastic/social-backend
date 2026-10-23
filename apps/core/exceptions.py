"""Transport-agnostic domain errors plus the DRF bridge that renders them.

Services raise these instead of DRF/HTTP exceptions so the domain layer stays
independent of the web framework. Only `api_exception_handler` knows about HTTP.
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(Exception):
    """Base class for every expected, client-facing failure."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "domain_error"
    message = "The request could not be completed."

    def __init__(self, message: str | None = None, *, details: dict | None = None):
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class ResourceNotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class PermissionDenied(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class InvalidInput(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "invalid_input"
    message = "The submitted data is invalid."


class Conflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state."


class StorageFailure(DomainError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "storage_failure"
    message = "The media storage provider could not process the file."


def _envelope(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def api_exception_handler(exc, context):
    """Render every error as the same `{"error": {...}}` envelope."""
    if isinstance(exc, DomainError):
        return Response(
            _envelope(exc.code, exc.message, exc.details),
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message, details = str(detail["detail"]), {}
    else:
        message, details = "The submitted data is invalid.", detail

    code = getattr(exc, "default_code", "error")
    response.data = _envelope(code, message, details)
    return response
