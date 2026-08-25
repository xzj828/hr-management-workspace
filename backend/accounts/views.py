from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import UserModelCredential
from .serializers import UserModelCredentialSerializer
from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def model_credential_view(request):
    credential, _ = UserModelCredential.objects.get_or_create(user=request.user)
    if request.method == "GET":
        return Response(UserModelCredentialSerializer(credential).data)
    if request.method == "DELETE":
        credential.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = UserModelCredentialSerializer(credential, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def model_credential_test_view(request):
    credential, _ = UserModelCredential.objects.get_or_create(user=request.user)
    try:
        result = OpenAICompatibleGateway(credential).test_connection()
    except ModelGatewayError as exc:
        response_status = status.HTTP_400_BAD_REQUEST if not exc.retryable else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({"detail": str(exc), "code": exc.code}, status=response_status)
    return Response(
        {
            "status": "available",
            "model": credential.model,
            "latency_ms": result.latency_ms,
        }
    )
