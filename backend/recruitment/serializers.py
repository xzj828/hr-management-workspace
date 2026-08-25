import uuid

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .models import (
    ApplicationStageHistory,
    AiProcessingTask,
    AutomationApproval,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    ConversationAction,
    ExecutionBatch,
    HumanAttention,
    JobApplication,
    JobRequirementDocument,
    JobRequirementDocumentVersion,
    JobStandardVersion,
    MessageSyncPolicy,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    StructuredResumeVersion,
    RpaTask,
    RpaTaskEvent,
    SearchCampaign,
    StepExecution,
    WorkflowTemplate,
    WorkflowVersion,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunEvent,
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
            "archived_at",
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
    class Meta:
        model = Candidate
        fields = ["id", "name", "phone", "email", "current_title", "current_city"]


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
            "archived_at",
        ]


class JobRequirementDocumentVersionSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.username", read_only=True)

    class Meta:
        model = JobRequirementDocumentVersion
        fields = [
            "id", "version", "original_name", "file_size", "sha256",
            "uploaded_by_name", "archived_at", "created_at",
        ]
        read_only_fields = fields


class JobRequirementDocumentSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    current_version = JobRequirementDocumentVersionSerializer(read_only=True)
    versions = JobRequirementDocumentVersionSerializer(many=True, read_only=True)

    class Meta:
        model = JobRequirementDocument
        fields = [
            "id", "job", "category", "category_label", "title", "current_version",
            "versions", "archived_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class JobStandardVersionSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    source_document_versions = JobRequirementDocumentVersionSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    published_by_name = serializers.CharField(source="published_by.username", read_only=True, allow_null=True)

    class Meta:
        model = JobStandardVersion
        fields = [
            "id", "job", "version", "status", "status_label", "source_document_versions",
            "criteria", "unresolved_questions", "model_name", "prompt_version",
            "created_by_name", "published_by_name", "published_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class MessageSyncPolicySerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="boss_account.name", read_only=True)

    class Meta:
        model = MessageSyncPolicy
        fields = [
            "id", "boss_account", "account_name", "enabled", "interval_minutes",
            "last_scheduled_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "account_name", "last_scheduled_at", "created_at", "updated_at"]

    def validate_boss_account(self, account):
        return _validate_authorized_account(account, self.context["request"].user)


class HumanAttentionSerializer(serializers.ModelSerializer):
    attention_type_label = serializers.CharField(source="get_attention_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    account_name = serializers.CharField(source="boss_account.name", read_only=True, allow_null=True)
    job_title = serializers.CharField(source="job.title", read_only=True, allow_null=True)
    candidate_name = serializers.CharField(source="application.candidate.name", read_only=True, allow_null=True)
    resolved_by_name = serializers.CharField(source="resolved_by.username", read_only=True, allow_null=True)

    class Meta:
        model = HumanAttention
        fields = [
            "id", "attention_type", "attention_type_label", "status", "status_label",
            "title", "detail", "priority", "boss_account", "account_name", "job",
            "job_title", "application", "candidate_name", "workflow_run", "workflow_node_run",
            "resolved_by_name", "resolution_note", "resolved_at", "archived_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class CandidateSerializer(serializers.ModelSerializer):
    applications = serializers.SerializerMethodField()
    resume_count = serializers.IntegerField(read_only=True)

    def get_applications(self, obj):
        applications = getattr(obj, "scoped_applications", None)
        if applications is None:
            applications = obj.applications.all()
        return JobApplicationSummarySerializer(applications, many=True).data

    class Meta:
        model = Candidate
        fields = [
            "id", "identity_key", "external_id", "name", "phone", "email",
            "current_title", "current_city", "applications", "resume_count",
            "is_demo", "created_at", "updated_at",
            "archived_at",
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
    resume_count = serializers.SerializerMethodField()
    other_applications = serializers.SerializerMethodField()

    def get_resume_count(self, obj):
        return sum(1 for resume in obj.resumes.all() if resume.archived_at is None)

    def get_other_applications(self, obj):
        from recruitment.services.access import accessible_jobs

        request = self.context.get("request")
        if request is None:
            return []
        applications = getattr(obj.candidate, "accessible_applications", None)
        if applications is None:
            applications = obj.candidate.applications.select_related("job", "owner").filter(
                job__in=accessible_jobs(request.user),
                archived_at__isnull=True,
            )
        applications = [application for application in applications if application.pk != obj.pk]
        return JobApplicationSummarySerializer(applications, many=True).data

    class Meta:
        model = JobApplication
        fields = [
            "id", "candidate", "job", "job_title", "source", "stage", "stage_label",
            "owner", "owner_name", "priority", "last_interaction_at", "is_demo",
            "stage_reason", "stage_history", "resume_count", "other_applications",
            "archived_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "candidate", "job", "job_title", "source", "stage_label", "owner",
            "owner_name", "priority", "last_interaction_at", "is_demo", "created_at", "updated_at",
            "resume_count", "other_applications", "archived_at",
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
    latest_structure_id = serializers.SerializerMethodField()
    intelligence_status = serializers.SerializerMethodField()

    def get_file_available(self, obj):
        return bool(obj.file and obj.file.storage.exists(obj.file.name))

    def get_preview_url(self, obj):
        return f"/api/recruitment/resumes/{obj.pk}/file/"

    def get_download_url(self, obj):
        return f"/api/recruitment/resumes/{obj.pk}/file/?download=1"

    def get_latest_structure_id(self, obj):
        latest = obj.structured_versions.order_by("-version").first()
        return latest.pk if latest else None

    def get_intelligence_status(self, obj):
        if obj.structured_versions.exists():
            return "completed"
        task = obj.ai_tasks.order_by("-created_at").first()
        return task.status if task else "not_started"

    class Meta:
        model = Resume
        fields = [
            "id", "candidate", "candidate_name", "application", "job_title", "original_name",
            "content_type", "file_size", "source", "source_label", "processing_status",
            "status_label", "file_available", "preview_url", "download_url", "is_demo",
            "sha256", "version", "external_id", "acquired_at", "created_at", "updated_at",
            "archived_at", "latest_structure_id", "intelligence_status",
        ]


class StructuredResumeVersionSerializer(serializers.ModelSerializer):
    resume_name = serializers.CharField(source="resume.original_name", read_only=True)

    class Meta:
        model = StructuredResumeVersion
        fields = [
            "id", "resume", "resume_name", "version", "data", "evidence", "warnings",
            "model_name", "prompt_version", "created_at",
        ]
        read_only_fields = fields


class ResumeAssessmentSerializer(serializers.ModelSerializer):
    resume = serializers.IntegerField(source="structured_resume.resume_id", read_only=True)
    resume_name = serializers.CharField(source="structured_resume.resume.original_name", read_only=True)
    standard_version = serializers.IntegerField(source="standard.version", read_only=True)
    recommendation_label = serializers.CharField(source="get_recommendation_display", read_only=True)

    class Meta:
        model = ResumeAssessment
        fields = [
            "id", "resume", "resume_name", "structured_resume", "standard", "standard_version",
            "version", "request_id", "total_score", "dimension_scores", "evidence", "gaps",
            "verification_questions", "confidence", "recommendation", "recommendation_label",
            "model_name", "prompt_version", "created_at",
        ]
        read_only_fields = fields


class AiProcessingTaskSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = AiProcessingTask
        fields = [
            "id", "kind", "kind_label", "status", "status_label", "job", "document_version",
            "resume", "standard", "progress", "attempt_count", "max_attempts", "available_at",
            "error_code", "error_message", "result_ref", "created_at", "updated_at",
        ]
        read_only_fields = fields


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
        fields = ["id", "name", "description", "active_version", "active_version_number", "archived_at", "created_at", "updated_at"]
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
            {
                "source": edge.source.node_key,
                "target": edge.target.node_key,
                "order": edge.order,
                "condition": edge.condition,
            }
            for edge in instance.edges.select_related("source", "target")
        ]
        return data


class WorkflowRunEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowRunEvent
        fields = ["id", "node_run", "level", "event", "message", "data", "created_at"]


class WorkflowNodeRunSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = WorkflowNodeRun
        fields = [
            "id", "node_key", "node_type", "status", "status_label", "config_snapshot",
            "input_snapshot", "output", "attempt", "error_code", "error_message",
            "started_at", "completed_at", "created_at", "updated_at",
        ]


class WorkflowRunSerializer(serializers.ModelSerializer):
    node_runs = WorkflowNodeRunSerializer(many=True, read_only=True)
    events = WorkflowRunEventSerializer(many=True, read_only=True)
    account_name = serializers.CharField(source="boss_account.name", read_only=True)
    version_number = serializers.IntegerField(source="version.version", read_only=True)
    template_name = serializers.CharField(source="version.template.name", read_only=True)

    class Meta:
        model = WorkflowRun
        fields = [
            "id", "version", "version_number", "template_name", "boss_account", "account_name",
            "job", "actor", "mode", "status", "idempotency_key", "graph_snapshot", "input_snapshot",
            "result", "error_code", "error_message", "started_at", "completed_at", "created_at",
            "updated_at", "node_runs", "events",
        ]
        read_only_fields = fields


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
            "archived_at",
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


class SearchCampaignSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="boss_account.name", read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)

    class Meta:
        model = SearchCampaign
        fields = [
            "id", "name", "boss_account", "account_name", "job", "job_title", "workflow_run",
            "source", "status", "target_resume_count", "max_scan_count", "scanned_count",
            "pulled_resume_count", "criteria", "stop_reason", "error_message", "created_by",
            "started_at", "completed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "scanned_count", "pulled_resume_count", "stop_reason", "error_message",
            "created_by", "started_at", "completed_at", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        account = attrs.get("boss_account", getattr(self.instance, "boss_account", None))
        job = attrs.get("job", getattr(self.instance, "job", None))
        if account and job and job.boss_account_id != account.pk:
            raise serializers.ValidationError({"job": "职位不属于所选 BOSS 账号"})
        if attrs.get("max_scan_count", getattr(self.instance, "max_scan_count", 0)) < attrs.get(
            "target_resume_count", getattr(self.instance, "target_resume_count", 0)
        ):
            raise serializers.ValidationError({"max_scan_count": "最大扫描人数不能小于目标简历数"})
        if account:
            _validate_authorized_account(account, self.context["request"].user)
        return attrs


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
