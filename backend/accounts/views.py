from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import UserModelCredential
from .serializers import UserModelCredentialSerializer


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
