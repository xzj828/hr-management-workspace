import uuid

from django.db import transaction
from rest_framework import serializers

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob
from .rpa.browser import browser_configuration, port_is_available


class BossAccountSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    login_status_label = serializers.CharField(source="get_login_status_display", read_only=True)

    class Meta:
        model = BossAccount
        fields = [
            "id", "name", "browser_type", "browser_profile", "browser_executable",
            "user_data_dir", "cdp_port", "daily_contact_limit", "status", "status_label",
            "login_status", "login_status_label", "verification_status", "last_checked_at", "active",
        ]
        read_only_fields = [
            "browser_profile", "browser_executable", "user_data_dir", "cdp_port", "status",
            "login_status", "verification_status", "last_checked_at",
        ]

    @transaction.atomic
    def create(self, validated_data):
        used_ports = set(BossAccount.objects.values_list("cdp_port", flat=True))
        port = next((candidate for candidate in range(53470, 53570) if candidate not in used_ports and port_is_available(candidate)), None)
        if port is None:
            raise serializers.ValidationError({"browser_type": "没有可用的浏览器调试端口"})

        profile = f"boss-{uuid.uuid4().hex[:12]}"
        try:
            config = browser_configuration(validated_data.get("browser_type", "chrome"), profile, port)
        except (ValueError, RuntimeError) as exc:
            raise serializers.ValidationError({"browser_type": str(exc)}) from exc

        return BossAccount.objects.create(
            **validated_data,
            browser_profile=profile,
            browser_executable=str(config.executable),
            user_data_dir=str(config.user_data_dir),
            cdp_port=config.port,
        )


class RecruitmentJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitmentJob
        fields = ["id", "boss_account", "external_id", "title", "department", "jd", "owner", "headcount", "status", "created_at", "updated_at"]


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = ["id", "identity_key", "external_id", "name", "phone", "email", "current_title", "current_city", "created_at", "updated_at"]


class JobApplicationSerializer(serializers.ModelSerializer):
    candidate = CandidateSerializer(read_only=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = JobApplication
        fields = ["id", "candidate", "job", "source", "stage", "stage_label", "owner", "priority", "last_interaction_at", "created_at", "updated_at"]
