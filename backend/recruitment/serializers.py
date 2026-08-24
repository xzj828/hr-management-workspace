import uuid

from django.db import transaction
from rest_framework import serializers

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob, Resume, RpaTask, RpaTaskEvent
from .rpa.browser import browser_configuration, port_is_available
from .rpa.tasks import create_task


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


class JobApplicationSummarySerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job.title", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True, allow_null=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = JobApplication
        fields = ["id", "job", "job_title", "stage", "stage_label", "owner_name", "updated_at"]


class CandidateSummarySerializer(serializers.ModelSerializer):
    resume_count = serializers.SerializerMethodField()

    def get_resume_count(self, obj):
        return obj.resumes.count()

    class Meta:
        model = Candidate
        fields = ["id", "name", "current_title", "current_city", "resume_count"]


class RecruitmentJobSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.username", read_only=True)
    account_name = serializers.CharField(source="boss_account.name", read_only=True, allow_null=True)
    candidate_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = RecruitmentJob
        fields = [
            "id", "boss_account", "account_name", "external_id", "title", "department",
            "jd", "owner", "owner_name", "headcount", "status", "candidate_count",
            "is_demo", "created_at", "updated_at",
        ]


class CandidateSerializer(serializers.ModelSerializer):
    applications = JobApplicationSummarySerializer(many=True, read_only=True)
    resume_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Candidate
        fields = [
            "id", "identity_key", "external_id", "name", "phone", "email",
            "current_title", "current_city", "applications", "resume_count",
            "is_demo", "created_at", "updated_at",
        ]


class JobApplicationSerializer(serializers.ModelSerializer):
    candidate = CandidateSummarySerializer(read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True, allow_null=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = JobApplication
        fields = [
            "id", "candidate", "job", "job_title", "source", "stage", "stage_label",
            "owner", "owner_name", "priority", "last_interaction_at", "is_demo",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "candidate", "job", "job_title", "source", "stage_label", "owner",
            "owner_name", "priority", "last_interaction_at", "is_demo", "created_at", "updated_at",
        ]


class ResumeSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.name", read_only=True)
    job_title = serializers.CharField(source="application.job.title", read_only=True, allow_null=True)
    status_label = serializers.CharField(source="get_processing_status_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    file_available = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    def get_file_available(self, obj):
        return bool(obj.file and obj.file.storage.exists(obj.file.name))

    def get_preview_url(self, obj):
        return f"/api/recruitment/resumes/{obj.pk}/file/"

    def get_download_url(self, obj):
        return f"/api/recruitment/resumes/{obj.pk}/file/?download=1"

    class Meta:
        model = Resume
        fields = [
            "id", "candidate", "candidate_name", "application", "job_title", "original_name",
            "content_type", "file_size", "source", "source_label", "processing_status",
            "status_label", "file_available", "preview_url", "download_url", "is_demo",
            "created_at", "updated_at",
        ]


class RpaTaskEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RpaTaskEvent
        fields = ["id", "level", "event", "message", "data", "created_at"]


class RpaTaskSerializer(serializers.ModelSerializer):
    events = RpaTaskEventSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    account_name = serializers.CharField(source="boss_account.name", read_only=True)

    class Meta:
        model = RpaTask
        fields = [
            "id", "boss_account", "account_name", "action", "status", "created_by_name",
            "worker", "approval", "execution_batch", "idempotency_key", "request_payload",
            "result", "error_code", "error_message",
            "lease_expires_at", "started_at", "completed_at", "created_at", "updated_at", "events",
        ]
        read_only_fields = [
            "status", "worker", "result", "error_code", "error_message", "lease_expires_at",
            "started_at", "completed_at", "created_at", "updated_at",
        ]
        extra_kwargs = {
            "idempotency_key": {"validators": [], "allow_blank": True, "allow_null": True},
        }

    def create(self, validated_data):
        task, created = create_task(
            account=validated_data["boss_account"],
            action=validated_data["action"],
            actor=self.context["request"].user,
            request_payload=validated_data.get("request_payload"),
            approval=validated_data.get("approval"),
            execution_batch=validated_data.get("execution_batch"),
            idempotency_key=validated_data.get("idempotency_key", ""),
            return_created=True,
        )
        task._was_existing = not created
        return task
