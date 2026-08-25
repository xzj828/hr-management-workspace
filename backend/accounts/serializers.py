from rest_framework import serializers

from .models import UserModelCredential, UserModelProfile
from .services.model_endpoint import ModelEndpointError, validate_model_api_url
from .services.model_profiles import (
    MAX_API_KEY_LENGTH,
    MIN_API_KEY_LENGTH,
    create_model_profile,
    update_legacy_model_credential,
    update_model_profile,
)


class UserModelCredentialSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=False,
        min_length=MIN_API_KEY_LENGTH,
        max_length=MAX_API_KEY_LENGTH,
        trim_whitespace=True,
    )
    api_url = serializers.URLField(required=False, allow_blank=False, max_length=500)
    model = serializers.CharField(required=False, allow_blank=False, max_length=120, trim_whitespace=True)
    has_api_key = serializers.SerializerMethodField()

    class Meta:
        model = UserModelCredential
        fields = ["api_url", "model", "api_key", "has_api_key", "key_last4", "updated_at"]
        read_only_fields = ["has_api_key", "key_last4", "updated_at"]

    def get_has_api_key(self, obj):
        return bool(obj.encrypted_api_key)

    def validate_api_url(self, value):
        try:
            return validate_model_api_url(value)
        except ModelEndpointError as exc:
            raise serializers.ValidationError(str(exc), code=exc.code) from exc

    def update(self, instance, validated_data):
        return update_legacy_model_credential(user=instance.user, values=validated_data)


class UserModelProfileSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=False,
        min_length=MIN_API_KEY_LENGTH,
        max_length=MAX_API_KEY_LENGTH,
        trim_whitespace=True,
    )
    make_active = serializers.BooleanField(write_only=True, required=False, default=False)
    has_api_key = serializers.SerializerMethodField()
    configured = serializers.SerializerMethodField()
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    api_url = serializers.URLField(allow_blank=False, max_length=500)
    model = serializers.CharField(max_length=120, trim_whitespace=True, allow_blank=False)

    class Meta:
        model = UserModelProfile
        fields = [
            "id", "name", "api_url", "model", "api_key", "has_api_key", "key_last4",
            "is_active", "configured", "make_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "has_api_key", "key_last4", "is_active", "configured", "created_at", "updated_at",
        ]

    def get_has_api_key(self, obj):
        return bool(obj.encrypted_api_key)

    def get_configured(self, obj):
        return bool(
            str(obj.api_url or "").strip()
            and str(obj.model or "").strip()
            and obj.encrypted_api_key
        )

    def validate_api_url(self, value):
        try:
            return validate_model_api_url(value)
        except ModelEndpointError as exc:
            raise serializers.ValidationError(str(exc), code=exc.code) from exc

    def validate(self, attrs):
        if self.instance is None and not attrs.get("api_key"):
            raise serializers.ValidationError({"api_key": "新增模型档案必须填写 API Key"})
        if self.instance is not None and attrs.get("make_active"):
            raise serializers.ValidationError({"make_active": "请使用模型激活接口切换当前模型"})
        request = self.context.get("request")
        if request and "name" in attrs:
            queryset = UserModelProfile.objects.filter(user=request.user, name__iexact=attrs["name"])
            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({"name": "当前账号已存在同名模型配置"})
        return attrs

    def create(self, validated_data):
        return create_model_profile(user=self.context["request"].user, values=validated_data)

    def update(self, instance, validated_data):
        return update_model_profile(
            user=self.context["request"].user,
            profile=instance,
            values=validated_data,
        )
