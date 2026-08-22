from rest_framework import serializers

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob


class BossAccountSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = BossAccount
        fields = ["id", "name", "browser_profile", "cdp_port", "daily_contact_limit", "status", "status_label", "active"]


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
