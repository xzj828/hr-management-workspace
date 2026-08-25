from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import UserModelProfile
from .serializers import UserModelCredentialSerializer, UserModelProfileSerializer
from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway
from .services.model_profiles import (
    ModelProfileConflict,
    ModelProfileInvalid,
    activate_model_profile,
    clear_legacy_model_credential,
    get_legacy_model_credential,
)


class ModelConnectionTestThrottle(UserRateThrottle):
    scope = "model_connection_test"


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def model_credential_view(request):
    credential = get_legacy_model_credential(user=request.user)
    if request.method == "GET":
        return Response(UserModelCredentialSerializer(credential).data)
    if request.method == "DELETE":
        clear_legacy_model_credential(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = UserModelCredentialSerializer(credential, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    try:
        serializer.save()
    except ModelProfileConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except ModelProfileInvalid as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ModelConnectionTestThrottle])
def model_credential_test_view(request):
    credential = get_legacy_model_credential(user=request.user)
    try:
        result = OpenAICompatibleGateway(
            credential,
            timeout=settings.MODEL_API_TEST_TIMEOUT_SECONDS,
        ).test_connection()
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


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def model_profile_list_view(request):
    if request.method == "GET":
        profiles = UserModelProfile.objects.filter(user=request.user)
        return Response(UserModelProfileSerializer(profiles, many=True).data)
    serializer = UserModelProfileSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    try:
        profile = serializer.save()
    except ModelProfileConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except ModelProfileInvalid as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(UserModelProfileSerializer(profile).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def model_profile_detail_view(request, profile_id):
    profile = get_object_or_404(UserModelProfile, pk=profile_id, user=request.user)
    if request.method == "GET":
        return Response(UserModelProfileSerializer(profile).data)
    serializer = UserModelProfileSerializer(
        profile,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    try:
        profile = serializer.save()
    except ModelProfileConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except ModelProfileInvalid as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(UserModelProfileSerializer(profile).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def model_profile_activate_view(request, profile_id):
    profile = get_object_or_404(UserModelProfile, pk=profile_id, user=request.user)
    try:
        profile = activate_model_profile(user=request.user, profile=profile)
    except ModelProfileInvalid as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(UserModelProfileSerializer(profile).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ModelConnectionTestThrottle])
def model_profile_test_view(request, profile_id):
    profile = get_object_or_404(UserModelProfile, pk=profile_id, user=request.user)
    try:
        result = OpenAICompatibleGateway(
            profile,
            timeout=settings.MODEL_API_TEST_TIMEOUT_SECONDS,
        ).test_connection()
    except ModelGatewayError as exc:
        response_status = status.HTTP_400_BAD_REQUEST if not exc.retryable else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({"detail": str(exc), "code": exc.code}, status=response_status)
    return Response(
        {
            "status": "available",
            "profile_id": profile.pk,
            "name": profile.name,
            "model": profile.model,
            "latency_ms": result.latency_ms,
        }
    )
