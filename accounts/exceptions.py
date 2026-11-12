from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return Response(
            {"detail": str(exc) or "Server error", "code": "server_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    data = response.data
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        response.data = {"detail": data["detail"], "code": getattr(exc, "default_code", "error")}
    elif isinstance(data, list):
        response.data = {"detail": data[0] if data else "Error", "code": "error", "errors": data}
    else:
        response.data = {"detail": "Validation failed", "code": "validation_error", "errors": data}
    return response
