import uuid

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .models import (
    ApplicationStageHistory,
    AutomationApproval,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    ConversationAction,
    ExecutionBatch,
    JobApplication,
    RecruitmentJob,
    Resume,
    RpaTask,
    RpaTaskEvent,
    StepExecution,
    WorkflowTemplate,
    WorkflowVersion,
)
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


class ApplicationStageHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True, allow_null=True)

    class Meta:
        model = ApplicationStageHistory
        fields = ["id", "from_stage", "to_stage", "source", "reason", "actor_name", "created_at"]


class JobApplicationSerializer(serializers.ModelSerializer):
    candidate = CandidateSummarySerializer(read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True, allow_null=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    stage_reason = serializers.CharField(write_only=True, required=False, allow_blank=True)
    stage_history = ApplicationStageHistorySerializer(many=True, read_only=True)

    class Meta:
        model = JobApplication
        fields = [
            "id", "candidate", "job", "job_title", "source", "stage", "stage_label",
            "owner", "owner_name", "priority", "last_interaction_at", "is_demo",
            "stage_reason", "stage_history", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "candidate", "job", "job_title", "source", "stage_label", "owner",
            "owner_name", "priority", "last_interaction_at", "is_demo", "created_at", "updated_at",
        ]

    def update(self, instance, validated_data):
        from recruitment.services.stages import change_stage_manually

        reason = validated_data.pop("stage_reason", "")
        requested_stage = validated_data.pop("stage", instance.stage)
        if requested_stage != instance.stage:
            change_stage_manually(
                application=instance,
                to_stage=requested_stage,
                actor=self.context["request"].user,
                reason=reason,
            )
            instance.refresh_from_db()
        return super().update(instance, validated_data)
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
            "sha256", "version", "external_id", "acquired_at", "created_at", "updated_at",
        ]


class CommunicationPrepareSerializer(serializers.Serializer):
    boss_account = serializers.PrimaryKeyRelatedField(queryset=BossAccount.objects.all())
    application_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=100)
    action = serializers.ChoiceField(choices=ConversationAction.Action.choices)
    message = serializers.CharField(min_length=1, max_length=1000)
    request_id = serializers.UUIDField()
    invitation = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        account = _validate_authorized_account(attrs["boss_account"], self.context["request"].user)
        applications = list(JobApplication.objects.select_related("candidate", "job").filter(pk__in=attrs["application_ids"]))
        if len(applications) != len(set(attrs["application_ids"])):
            raise serializers.ValidationError({"application_ids": "部分候选人不存在"})
        if any(application.job.boss_account_id != account.pk for application in applications):
            raise serializers.ValidationError({"application_ids": "候选人与所选账号不匹配"})
        invitation = attrs.get("invitation") or {}
        if attrs["action"] == ConversationAction.Action.SEND_INTERVIEW:
            required = ["interview_at", "mode", "location", "contact_name"]
            if any(not invitation.get(field) for field in required):
                raise serializers.ValidationError({"invitation": "面试时间、形式、地址和联系人必填"})
        attrs["applications"] = applications
        return attrs


class ConversationActionSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="application.candidate.name", read_only=True)
    job_title = serializers.CharField(source="application.job.title", read_only=True)

    class Meta:
        model = ConversationAction
        fields = [
            "id", "application", "candidate_name", "job_title", "boss_account", "action", "status",
            "message_snapshot", "target_snapshot", "approval", "batch", "result", "error_code",
            "error_message", "created_at", "updated_at",
        ]
        read_only_fields = fields


class StepExecutionSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField()
    action_id = serializers.SerializerMethodField()

    def get_candidate_name(self, obj):
        action = getattr(obj, "conversation_action", None)
        return action.application.candidate.name if action else obj.target_payload.get("name", "")

    def get_action_id(self, obj):
        action = getattr(obj, "conversation_action", None)
        return str(action.pk) if action else ""

    class Meta:
        model = StepExecution
        fields = ["id", "action_id", "candidate_name", "status", "result", "error_code", "error_message", "created_at", "updated_at"]


class ExecutionBatchSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="boss_account.name", read_only=True)
    steps = StepExecutionSerializer(many=True, read_only=True)

    class Meta:
        model = ExecutionBatch
        fields = [
            "id", "approval", "boss_account", "account_name", "action", "status", "total_items",
            "succeeded_items", "failed_items", "steps", "created_at", "updated_at",
        ]


class WorkflowTemplateSerializer(serializers.ModelSerializer):
    active_version_number = serializers.IntegerField(source="active_version.version", read_only=True, allow_null=True)

    class Meta:
        model = WorkflowTemplate
        fields = ["id", "name", "description", "active_version", "active_version_number", "created_at", "updated_at"]
        read_only_fields = ["id", "active_version", "active_version_number", "created_at", "updated_at"]


class WorkflowVersionSerializer(serializers.ModelSerializer):
    nodes = serializers.JSONField(write_only=True)
    edges = serializers.JSONField(write_only=True)

    class Meta:
        model = WorkflowVersion
        fields = ["id", "template", "version", "status", "boss_account", "nodes", "edges", "created_at"]
        read_only_fields = ["id", "version", "status", "created_at"]

    def create(self, validated_data):
        from recruitment.services.workflows import create_version

        request = self.context["request"]
        account = _validate_authorized_account(validated_data["boss_account"], request.user)
        template = validated_data["template"]
        if template.created_by_id != request.user.pk and not request.user.is_superuser:
            raise PermissionDenied("无权修改该流程")
        return create_version(
            template=template,
            boss_account=account,
            nodes=validated_data.pop("nodes"),
            edges=validated_data.pop("edges"),
            actor=request.user,
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["nodes"] = [
            {"key": node.node_key, "type": node.node_type, "label": node.label, "position": node.position, "config": node.config}
            for node in instance.nodes.all()
        ]
        data["edges"] = [
            {"source": edge.source.node_key, "target": edge.target.node_key}
            for edge in instance.edges.select_related("source", "target")
        ]
        return data


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


class PositionSyncRequestSerializer(serializers.Serializer):
    boss_account = serializers.PrimaryKeyRelatedField(queryset=BossAccount.objects.all())
    request_id = serializers.UUIDField()

    def validate_boss_account(self, account):
        user = self.context["request"].user
        if not user.is_superuser and not account.authorized_users.filter(pk=user.pk).exists():
            raise PermissionDenied("无权操作该 BOSS 账号")
        if not account.active:
            raise serializers.ValidationError("该 BOSS 账号已停用")
        return account


def _validate_authorized_account(account, user):
    if not user.is_superuser and not account.authorized_users.filter(pk=user.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")
    if not account.active:
        raise serializers.ValidationError("该 BOSS 账号已停用")
    return account


class CandidateDiscoverySerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="boss_account.name", read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    identity_quality_label = serializers.CharField(source="get_identity_quality_display", read_only=True)
    imported_candidate_name = serializers.CharField(
        source="imported_candidate.name", read_only=True, allow_null=True
    )

    class Meta:
        model = CandidateDiscovery
        fields = [
            "id", "boss_account", "account_name", "job", "job_title", "source", "source_label",
            "external_id", "fingerprint", "identity_quality", "identity_quality_label",
            "display_name", "current_title", "city", "experience", "education", "advantage",
            "tags", "contact_hint", "imported_candidate", "imported_candidate_name",
            "expires_at", "imported_at", "created_at", "updated_at",
        ]


class CandidateDiscoverySearchSerializer(serializers.Serializer):
    boss_account = serializers.PrimaryKeyRelatedField(queryset=BossAccount.objects.all())
    job = serializers.PrimaryKeyRelatedField(queryset=RecruitmentJob.objects.all())
    mode = serializers.ChoiceField(choices=["recommend", "search"])
    keyword = serializers.CharField(max_length=20, allow_blank=True, required=False, default="")
    request_id = serializers.UUIDField()

    def validate(self, attrs):
        account = _validate_authorized_account(attrs["boss_account"], self.context["request"].user)
        if attrs["job"].boss_account_id != account.pk:
            raise serializers.ValidationError({"job": "职位不属于所选 BOSS 账号"})
        return attrs


class DeepMatchPrepareSerializer(serializers.Serializer):
    boss_account = serializers.PrimaryKeyRelatedField(queryset=BossAccount.objects.all())
    job = serializers.PrimaryKeyRelatedField(queryset=RecruitmentJob.objects.all())
    core = serializers.ListField(
        child=serializers.CharField(max_length=200), required=False, default=list, max_length=10
    )
    bonus = serializers.ListField(
        child=serializers.CharField(max_length=200), required=False, default=list, max_length=10
    )
    request_id = serializers.UUIDField()

    def validate(self, attrs):
        account = _validate_authorized_account(attrs["boss_account"], self.context["request"].user)
        if attrs["job"].boss_account_id != account.pk:
            raise serializers.ValidationError({"job": "职位不属于所选 BOSS 账号"})
        attrs["core"] = [value.strip() for value in attrs["core"] if value.strip()]
        attrs["bonus"] = [value.strip() for value in attrs["bonus"] if value.strip()]
        return attrs


class CandidateDiscoveryImportSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)


class AutomationApprovalSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="boss_account.name", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.username", read_only=True, allow_null=True)

    class Meta:
        model = AutomationApproval
        fields = [
            "id", "idempotency_key", "action", "boss_account", "account_name", "payload",
            "item_count", "status", "approved_by_name", "expires_at", "approved_at", "created_at",
        ]
        read_only_fields = fields
