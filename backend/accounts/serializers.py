from rest_framework import serializers

from .crypto import encrypt_secret
from .models import UserModelCredential


class UserModelCredentialSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False)
    has_api_key = serializers.SerializerMethodField()

    class Meta:
        model = UserModelCredential
        fields = ["api_url", "model", "api_key", "has_api_key", "key_last4", "updated_at"]
        read_only_fields = ["has_api_key", "key_last4", "updated_at"]

    def get_has_api_key(self, obj):
        return bool(obj.encrypted_api_key)

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        if api_key:
            instance.encrypted_api_key = encrypt_secret(api_key)
            instance.key_last4 = api_key[-4:]
        return super().update(instance, validated_data)
