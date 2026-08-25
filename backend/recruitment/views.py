from dataclasses import asdict
from datetime import timedelta
import uuid

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .demo_data import clear_demo_data, demo_status, load_demo_data
from .models import (
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
    RecruitmentAuditLog,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    StructuredResumeVersion,
    RpaTask,
    RpaWorker,
    SearchCampaign,
    WorkflowTemplate,
    WorkflowVersion,
    WorkflowNodeRun,
    WorkflowRun,
)
from .permissions import RecruitmentWritePermission
from .rpa.tasks import cancel_task, create_task, retry_task
from .rpa.status import inspect_boss_status
from .serializers import (
    BossAccountSerializer,
    AutomationApprovalSerializer,
    CandidateDiscoveryImportSerializer,
    CandidateDiscoverySearchSerializer,
    CandidateDiscoverySerializer,
    CandidateSerializer,
    CommunicationPrepareSerializer,
    ConversationActionSerializer,
    DeepMatchPrepareSerializer,
    ExecutionBatchSerializer,
    JobApplicationSerializer,
    JobRequirementDocumentSerializer,
    JobRequirementDocumentVersionSerializer,
    JobStandardVersionSerializer,
    HumanAttentionSerializer,
    MessageSyncPolicySerializer,
    PositionSyncRequestSerializer,
    RecruitmentJobSerializer,
    ResumeSerializer,
    ResumeAssessmentSerializer,
    StructuredResumeVersionSerializer,
    AiProcessingTaskSerializer,
    RpaTaskSerializer,
    SearchCampaignSerializer,
    WorkflowTemplateSerializer,
    WorkflowVersionSerializer,
    WorkflowRunSerializer,
)
from .services.approvals import approve, reject
from .services.access import accessible_jobs
from .services.communications import materialize_communication_batch, prepare_communication
from .services.communications import _identity_snapshot
from .services.discovery import import_discoveries
from .services.workflows import enable_version
from .services.account_status import apply_account_observation
from .services.dashboard import build_recruitment_dashboard
from .services.lifecycle import LifecycleConflict, archive_object, restore_object
from .services.job_documents import create_document, create_document_version, set_current_version
from .services.ai_tasks import (
    enqueue_job_standard,
    enqueue_resume_score,
    enqueue_resume_structure,
    retry_task as retry_ai_task,
)
from .services.job_standards import publish_standard, update_standard_draft
from .services.human_attention import archive_attention, resolve_attention
from .services.standard_workflows import create_standard_workflow
from .services.workflow_nodes import execute_workflow_node
from .services.workflow_runtime import HUMAN_NODE_TYPES, WorkflowConflict, advance_run, cancel_run, create_run, decide_node, pause_run, resume_run, retry_node
from .services.search_campaigns import prepare_search_campaign, start_search_campaign, stop_search_campaign


def _materialize_deep_match_task(*, approval, actor, workflow_node_run=None):
    payload = approval.payload if isinstance(approval.payload, dict) else {}
    node_id = payload.get("workflow_node_run_id")
    node = workflow_node_run
    if node is None and node_id:
        node = WorkflowNodeRun.objects.select_for_update().select_related("run").filter(pk=node_id).first()
    if node is not None:
        expected_job_id = node.run.job_id or node.run.input_snapshot.get("job")
        if (
            str(node.pk) != str(node_id)
            or node.node_type != "deep_search"
            or node.run.boss_account_id != approval.boss_account_id
            or node.run.actor_id != approval.created_by_id
            or expected_job_id != payload.get("job")
            or node.attempt != payload.get("workflow_node_attempt")
            or str((node.output or {}).get("approval_id", "")) != str(approval.pk)
        ):
            raise ValidationError("深度匹配确认与流程节点的冻结范围不一致")
    elif node_id:
        raise ValidationError("深度匹配确认引用的流程节点不存在")
    return create_task(
        account=approval.boss_account,
        action=RpaTask.Action.DEEP_MATCH,
        actor=actor,
        approval=approval,
        workflow_node_run=node,
        request_payload={
            "job": payload["job"],
            "job_title": payload["job_title"],
            "core": payload.get("core", []),
            "bonus": payload.get("bonus", []),
            "criteria": {
                "mode": "deep_search",
                "core": payload.get("core", []),
                "bonus": payload.get("bonus", []),
            },
        },
        idempotency_key=f"deep-match-task:{approval.pk}",
        creation_path="deep_match_approval",
        return_created=True,
    )


class ArchivableViewSetMixin:
    def get_queryset(self):
        queryset = super().get_queryset()
        archived = self.request.query_params.get("archived") == "1"
        return queryset.filter(archived_at__isnull=not archived)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        instance = archive_object(instance=self.get_object(), actor=request.user)
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        instance = restore_object(instance=self.get_object(), actor=request.user)
        return Response(self.get_serializer(instance).data)


def requested_open_job(request):
    raw_job_id = request.query_params.get("job")
    if not raw_job_id:
        return None
    if not raw_job_id.isdigit():
        raise ValidationError({"job": "职位参数无效"})
    job = accessible_jobs(request.user).filter(
        pk=int(raw_job_id),
        status=RecruitmentJob.Status.OPEN,
        archived_at__isnull=True,
    ).first()
    if not job:
        raise NotFound("职位不存在、已关闭或不可访问")
    return job


class BossAccountViewSet(ArchivableViewSetMixin, viewsets.ModelViewSet):
    queryset = BossAccount.objects.all().order_by("name")
    serializer_class = BossAccountSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(authorized_users=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        account = serializer.save()
        account.authorized_users.add(self.request.user)
        create_task(
            account=account,
            action=RpaTask.Action.CHECK_STATUS,
            actor=self.request.user,
            request_payload={"open_login": True},
        )

    @action(detail=True, methods=["post"], url_path="check-status")
    def check_status(self, request, pk=None):
        account = self.get_object()
        observation = inspect_boss_status(account.cdp_port)
        account = apply_account_observation(
            account=account,
            login_status=observation.login_status,
            verification_status=observation.verification_status,
            detail=observation.detail,
        )
        data = self.get_serializer(account).data
        data["status_detail"] = observation.detail
        return Response(data)


class RecruitmentJobViewSet(ArchivableViewSetMixin, viewsets.ModelViewSet):
    queryset = RecruitmentJob.objects.select_related("boss_account", "owner").annotate(
        candidate_count=Count("applications", distinct=True)
    ).order_by("-updated_at")
    serializer_class = RecruitmentJobSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(pk__in=accessible_jobs(self.request.user))
        job_status = self.request.query_params.get("status")
        if job_status:
            queryset = queryset.filter(status=job_status)
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset

    @action(detail=False, methods=["post"], url_path="sync")
    def sync(self, request):
        serializer = PositionSyncRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        account = serializer.validated_data["boss_account"]
        request_id = serializer.validated_data["request_id"]
        task, created = create_task(
            account=account,
            action=RpaTask.Action.SYNC_POSITIONS,
            actor=request.user,
            idempotency_key=f"position-sync:{account.pk}:{request_id}",
            return_created=True,
        )
        return Response(
            {"task_id": str(task.pk), "status": task.status},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class JobRequirementDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobRequirementDocument.objects.select_related(
        "job", "current_version", "created_by"
    ).prefetch_related("versions__uploaded_by")
    serializer_class = JobRequirementDocumentSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(
            job_id__in=accessible_jobs(self.request.user),
            archived_at__isnull=True,
        )
        job_id = self.request.query_params.get("job")
        if job_id:
            if not queryset.filter(job_id=job_id).exists() and not RecruitmentJob.objects.filter(
                pk=job_id,
                requirement_documents__isnull=False,
            ).exists():
                if not accessible_jobs(self.request.user).filter(pk=job_id).exists():
                    raise NotFound("职位不存在或无权访问")
            queryset = queryset.filter(job_id=job_id)
        return queryset

    def create(self, request, *args, **kwargs):
        job = accessible_jobs(request.user).filter(pk=request.data.get("job")).first()
        if job is None:
            raise NotFound("职位不存在或无权访问")
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "请选择 Word 文档"})
        category = str(request.data.get("category", ""))
        if category not in JobRequirementDocument.Category.values:
            raise ValidationError({"category": "文档用途无效"})
        title = str(request.data.get("title", "")).strip()
        if not title:
            raise ValidationError({"title": "文档名称不能为空"})
        try:
            document = create_document(
                job=job,
                category=category,
                title=title,
                upload=upload,
                actor=request.user,
            )
        except ValueError as exc:
            raise ValidationError({"file": str(exc)}) from exc
        return Response(self.get_serializer(document).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        document = self.get_object()
        document.archived_at = timezone.now()
        document.save(update_fields=["archived_at", "updated_at"])
        RecruitmentAuditLog.objects.create(
            actor=request.user, boss_account=document.job.boss_account,
            action="job_requirement_document_archived", target_id=str(document.pk),
        )
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"], url_path="versions")
    def add_version(self, request, pk=None):
        document = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "请选择 Word 文档"})
        try:
            document = create_document_version(document=document, upload=upload, actor=request.user)
        except ValueError as exc:
            raise ValidationError({"file": str(exc)}) from exc
        return Response(self.get_serializer(document).data, status=status.HTTP_201_CREATED)


class JobRequirementDocumentVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobRequirementDocumentVersion.objects.select_related("document__job", "uploaded_by")
    serializer_class = JobRequirementDocumentVersionSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        return super().get_queryset().filter(document__job_id__in=accessible_jobs(self.request.user))

    @action(detail=True, methods=["post"], url_path="make-current")
    def make_current(self, request, pk=None):
        version = self.get_object()
        document = set_current_version(version=version)
        return Response(JobRequirementDocumentSerializer(document).data)

    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        version = self.get_object()
        try:
            handle = version.file.open("rb")
        except (FileNotFoundError, OSError):
            raise NotFound("Word 文档文件不存在")
        return FileResponse(
            handle,
            as_attachment=True,
            filename=version.original_name,
            content_type="application/octet-stream",
        )


class JobStandardVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobStandardVersion.objects.select_related(
        "job__boss_account", "created_by", "published_by"
    ).prefetch_related("source_document_versions__uploaded_by")
    serializer_class = JobStandardVersionSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(job_id__in=accessible_jobs(self.request.user))
        job_id = self.request.query_params.get("job")
        if job_id:
            if not accessible_jobs(self.request.user).filter(pk=job_id).exists():
                raise NotFound("职位不存在或无权访问")
            queryset = queryset.filter(job_id=job_id)
        return queryset

    def update(self, request, *args, **kwargs):
        standard = self.get_object()
        if standard.status != JobStandardVersion.Status.DRAFT:
            return Response({"detail": "已启用或历史评分标准不可直接修改"}, status=status.HTTP_409_CONFLICT)
        try:
            updated = update_standard_draft(
                standard=standard,
                criteria=request.data.get("criteria"),
                unresolved_questions=request.data.get("unresolved_questions", standard.unresolved_questions),
                actor=request.user,
            )
        except ValueError as exc:
            raise ValidationError({"criteria": str(exc)}) from exc
        return Response(self.get_serializer(updated).data)

    partial_update = update

    @action(detail=False, methods=["post"])
    def generate(self, request):
        job = accessible_jobs(request.user).filter(pk=request.data.get("job"), archived_at__isnull=True).first()
        if not job:
            raise NotFound("职位不存在或无权访问")
        try:
            task, created = enqueue_job_standard(
                job=job, requested_by=request.user, request_id=request.data.get("request_id") or None
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {"task_id": str(task.pk), "status": task.status},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        try:
            standard = publish_standard(standard=self.get_object(), actor=request.user)
        except ValueError as exc:
            raise ValidationError({"criteria": str(exc)}) from exc
        return Response(self.get_serializer(standard).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        standard = self.get_object()
        task = AiProcessingTask.objects.filter(
            job=standard.job,
            kind=AiProcessingTask.Kind.JOB_STANDARD,
            status__in=[AiProcessingTask.Status.FAILED, AiProcessingTask.Status.WAITING_CONFIG],
        ).order_by("-created_at").first()
        if not task:
            return Response({"detail": "没有可重试的岗位标准任务"}, status=status.HTTP_409_CONFLICT)
        try:
            task = retry_ai_task(task=task, requested_by=request.user)
        except (PermissionError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"task_id": str(task.pk), "status": task.status})


class MessageSyncPolicyViewSet(viewsets.ModelViewSet):
    queryset = MessageSyncPolicy.objects.select_related("boss_account")
    serializer_class = MessageSyncPolicySerializer
    permission_classes = [RecruitmentWritePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(boss_account__authorized_users=self.request.user)
        return queryset.distinct().order_by("boss_account_id")


class HumanAttentionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HumanAttention.objects.select_related(
        "boss_account", "job", "application__candidate", "workflow_run", "workflow_node_run", "resolved_by"
    )
    serializer_class = HumanAttentionSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(
                Q(boss_account__authorized_users=self.request.user)
                | Q(boss_account__isnull=True, job__owner=self.request.user)
            )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset.distinct()

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        attention = resolve_attention(
            attention=self.get_object(),
            actor=request.user,
            note=str(request.data.get("note", "")),
            approved=request.data.get("approved", True) is not False,
        )
        return Response(self.get_serializer(attention).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return Response(self.get_serializer(archive_attention(attention=self.get_object())).data)


class CandidateViewSet(ArchivableViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Candidate.objects.prefetch_related(
        "applications__job", "applications__owner", "resumes"
    ).annotate(resume_count=Count("resumes", distinct=True)).order_by("-updated_at")
    serializer_class = CandidateSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(
                Q(applications__job__boss_account__authorized_users=self.request.user)
                | Q(applications__job__boss_account__isnull=True, applications__job__owner=self.request.user)
            ).distinct()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(current_title__icontains=search)
                | Q(current_city__icontains=search)
            )
        job = requested_open_job(self.request)
        if job:
            queryset = queryset.filter(applications__job=job).prefetch_related(
                Prefetch(
                    "applications",
                    queryset=JobApplication.objects.select_related("job", "owner").filter(job=job),
                    to_attr="scoped_applications",
                )
            )
        if self.request.query_params.get("stage"):
            queryset = queryset.filter(applications__stage=self.request.query_params["stage"])
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset.distinct()


class CandidateDiscoveryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CandidateDiscovery.objects.select_related(
        "boss_account", "job", "imported_candidate"
    ).all()
    serializer_class = CandidateDiscoverySerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(expires_at__gt=timezone.now())
        if not self.request.user.is_superuser:
            queryset = queryset.filter(boss_account__authorized_users=self.request.user)
        for field in ("boss_account", "job", "source"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        imported = self.request.query_params.get("imported")
        if imported == "true":
            queryset = queryset.filter(imported_candidate__isnull=False)
        elif imported == "false":
            queryset = queryset.filter(imported_candidate__isnull=True)
        return queryset.distinct()

    @action(detail=False, methods=["post"])
    def search(self, request):
        serializer = CandidateDiscoverySearchSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = data["boss_account"]
        job = data["job"]
        mode = data["mode"]
        task, created = create_task(
            account=account,
            action=(
                RpaTask.Action.RECOMMEND_CANDIDATES
                if mode == "recommend"
                else RpaTask.Action.SEARCH_CANDIDATES
            ),
            actor=request.user,
            request_payload={
                "job": job.pk,
                "job_title": job.title,
                "keyword": data.get("keyword", ""),
                "criteria": {"mode": mode, "keyword": data.get("keyword", "")},
            },
            idempotency_key=f"candidate-discovery:{account.pk}:{mode}:{data['request_id']}",
            return_created=True,
        )
        return Response(
            {"task_id": str(task.pk), "status": task.status},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="prepare-deep-match")
    def prepare_deep_match(self, request):
        serializer = DeepMatchPrepareSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = data["boss_account"]
        job = data["job"]
        key = f"deep-match:{account.pk}:{data['request_id']}"
        approval, created = AutomationApproval.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "action": AutomationApproval.Action.DEEP_MATCH,
                "boss_account": account,
                "created_by": request.user,
                "payload": {
                    "job": job.pk,
                    "job_title": job.title,
                    "core": data["core"],
                    "bonus": data["bonus"],
                    "request_id": str(data["request_id"]),
                    "estimated_consumption": 1,
                },
                "expires_at": timezone.now() + timedelta(minutes=15),
            },
        )
        if approval.created_by_id != request.user.pk or approval.boss_account_id != account.pk:
            return Response({"detail": "确认请求标识已被占用"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            AutomationApprovalSerializer(approval).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="import-selected")
    def import_selected(self, request):
        serializer = CandidateDiscoveryImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        discoveries = list(self.get_queryset().filter(pk__in=ids))
        if len(discoveries) != len(set(ids)):
            return Response(
                {"detail": "部分候选人不存在或无权操作"},
                status=status.HTTP_403_FORBIDDEN,
            )
        result = import_discoveries(discoveries=discoveries, actor=request.user)
        return Response(asdict(result))


class AutomationApprovalViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AutomationApproval.objects.select_related("boss_account", "created_by", "approved_by")
    serializer_class = AutomationApprovalSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(boss_account__authorized_users=self.request.user)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        approval_target = self.get_object()
        try:
            approval = approve(approval=approval_target, actor=request.user)
        except ValidationError:
            approval_target.refresh_from_db()
            if approval_target.status == AutomationApproval.Status.EXPIRED:
                return Response({"detail": "该确认项已过期"}, status=status.HTTP_400_BAD_REQUEST)
            raise
        task = None
        created = False
        if approval.action == AutomationApproval.Action.DEEP_MATCH:
            task, created = _materialize_deep_match_task(approval=approval, actor=request.user)
        elif approval.action == AutomationApproval.Action.VIEW_ONLINE_RESUME:
            payload = approval.payload
            task, created = create_task(
                account=approval.boss_account,
                action=RpaTask.Action.VIEW_ONLINE_RESUME,
                actor=request.user,
                approval=approval,
                request_payload={
                    "application_id": payload["application_id"],
                    "target": payload["target"],
                },
                idempotency_key=f"online-resume-task:{approval.pk}",
                creation_path="view_online_resume_approval",
                return_created=True,
            )
        elif approval.action == AutomationApproval.Action.SEARCH_AND_PULL_RESUMES:
            campaign = SearchCampaign.objects.filter(
                pk=approval.payload.get("campaign_id"),
                boss_account=approval.boss_account,
            ).first()
            if campaign is None:
                raise ValidationError("主动寻访任务不存在")
            task = start_search_campaign(
                campaign=campaign,
                actor=request.user,
                approval=approval,
            )
            created = True
        response = AutomationApprovalSerializer(approval).data
        if approval.action in {
            AutomationApproval.Action.GREET,
            AutomationApproval.Action.REQUEST_RESUME,
            AutomationApproval.Action.SEND_INTERVIEW,
        }:
            batch = materialize_communication_batch(approval=approval, actor=request.user)
            response["batch"] = ExecutionBatchSerializer(batch).data
            created = True
        if task:
            response["task_id"] = str(task.pk)
            response["task_status"] = task.status
        return Response(response, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class JobApplicationViewSet(
    ArchivableViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = JobApplication.objects.select_related(
        "candidate", "job", "owner"
    ).prefetch_related("candidate__resumes", "resumes").order_by("-updated_at")
    serializer_class = JobApplicationSerializer
    permission_classes = [RecruitmentWritePermission]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset().filter(job__in=accessible_jobs(self.request.user))
        queryset = queryset.prefetch_related(
            Prefetch(
                "candidate__applications",
                queryset=JobApplication.objects.select_related("job", "owner").filter(
                    job__in=accessible_jobs(self.request.user),
                    archived_at__isnull=True,
                ),
                to_attr="accessible_applications",
            )
        )
        job = requested_open_job(self.request)
        if job:
            queryset = queryset.filter(job=job)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(candidate__name__icontains=search)
                | Q(candidate__current_title__icontains=search)
                | Q(candidate__current_city__icontains=search)
            )
        if self.request.query_params.get("stage"):
            queryset = queryset.filter(stage=self.request.query_params["stage"])
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset


class ConversationActionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConversationAction.objects.select_related(
        "application__candidate", "application__job", "boss_account"
    ).all()
    serializer_class = ConversationActionSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(boss_account__authorized_users=self.request.user)
        return queryset.distinct()

    @action(detail=False, methods=["post"])
    def prepare(self, request):
        serializer = CommunicationPrepareSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        approval = prepare_communication(
            account=data["boss_account"],
            applications=data["applications"],
            action=data["action"],
            message=data["message"],
            actor=request.user,
            request_id=data["request_id"],
            invitation=data.get("invitation"),
        )
        return Response(
            {"approval_id": str(approval.pk), "status": approval.status, "item_count": approval.item_count},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="prepare-online-resume")
    def prepare_online_resume(self, request):
        application = JobApplication.objects.select_related("candidate", "job__boss_account").filter(
            pk=request.data.get("application_id")
        ).first()
        if application is None or application.job.boss_account_id is None:
            return Response({"detail": "候选人或 BOSS 账号不存在"}, status=status.HTTP_400_BAD_REQUEST)
        account = application.job.boss_account
        if not request.user.is_superuser and not account.authorized_users.filter(pk=request.user.pk).exists():
            return Response({"detail": "无权操作该 BOSS 账号"}, status=status.HTTP_403_FORBIDDEN)
        request_id = str(request.data.get("request_id", "")).strip()
        if not request_id:
            return Response({"detail": "request_id 必填"}, status=status.HTTP_400_BAD_REQUEST)
        target = _identity_snapshot(application, account)
        if not target.get("fingerprint") or not target.get("verification"):
            return Response(
                {"detail": "候选人缺少可刷新的唯一身份来源，请转人工查看"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        approval, created = AutomationApproval.objects.get_or_create(
            idempotency_key=f"online-resume:{account.pk}:{request_id}",
            defaults={
                "action": AutomationApproval.Action.VIEW_ONLINE_RESUME,
                "boss_account": account,
                "created_by": request.user,
                "payload": {
                    "application_id": application.pk,
                    "target": target,
                    "estimated_consumption": 1,
                },
                "expires_at": timezone.now() + timedelta(minutes=15),
            },
        )
        return Response(
            AutomationApprovalSerializer(approval).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ExecutionBatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExecutionBatch.objects.select_related("boss_account", "approval").prefetch_related(
        "steps__conversation_action__application__candidate"
    )
    serializer_class = ExecutionBatchSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(boss_account__authorized_users=self.request.user)
        return queryset.distinct()


class WorkflowTemplateViewSet(ArchivableViewSetMixin, viewsets.ModelViewSet):
    queryset = WorkflowTemplate.objects.select_related("active_version", "created_by").all()
    serializer_class = WorkflowTemplateSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset if self.request.user.is_superuser else queryset.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="standard")
    def standard(self, request):
        account = BossAccount.objects.filter(pk=request.data.get("boss_account"), active=True).first()
        if account is None:
            raise ValidationError({"boss_account": "BOSS 账号不存在或已停用"})
        if not request.user.is_superuser and not account.authorized_users.filter(pk=request.user.pk).exists():
            raise ValidationError({"boss_account": "无权操作该 BOSS 账号"})
        config = request.data.get("config") if isinstance(request.data.get("config"), dict) else {}
        try:
            template, version = create_standard_workflow(
                kind=str(request.data.get("kind", "")),
                account=account,
                actor=request.user,
                config=config,
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError({"config": str(exc)}) from exc
        return Response(
            {
                "template": self.get_serializer(template).data,
                "version": WorkflowVersionSerializer(version, context=self.get_serializer_context()).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WorkflowVersionViewSet(viewsets.ModelViewSet):
    queryset = WorkflowVersion.objects.select_related("template", "boss_account").prefetch_related("nodes", "edges__source", "edges__target")
    serializer_class = WorkflowVersionSerializer
    permission_classes = [RecruitmentWritePermission]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(template__archived_at__isnull=self.request.query_params.get("archived") != "1")
        return queryset if self.request.user.is_superuser else queryset.filter(template__created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        version = self.get_object()
        if version.status != WorkflowVersion.Status.DRAFT:
            raise LifecycleConflict("已启用或已停用的流程版本需要保留审计记录，不能直接删除")
        if version.template.active_version_id == version.pk:
            raise LifecycleConflict("当前启用版本不能删除，请先停用流程")
        RecruitmentAuditLog.objects.create(
            actor=request.user,
            boss_account=version.boss_account,
            action="workflow_draft_deleted",
            target_id=str(version.pk),
            detail={"template_id": version.template_id, "version": version.version},
        )
        version.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        version = enable_version(version=self.get_object(), actor=request.user)
        return Response(self.get_serializer(version).data)

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        version = self.get_object()
        mode = request.data.get("mode", WorkflowRun.Mode.DRY_RUN)
        request_id = str(request.data.get("request_id", "")).strip()
        if not request_id:
            raise ValidationError({"request_id": "运行请求标识必填"})
        if mode == WorkflowRun.Mode.FORMAL:
            if version.status != WorkflowVersion.Status.ENABLED:
                raise ValidationError("正式运行只能使用已启用版本")
            if request.data.get("confirm") is not True:
                raise ValidationError("正式运行前必须明确确认")
            if version.boss_account.login_status != BossAccount.LoginStatus.READY:
                raise ValidationError("BOSS 账号尚未登录或需要人工验证")
        job = None
        job_id = request.data.get("job")
        if job_id:
            job = RecruitmentJob.objects.filter(pk=job_id, boss_account=version.boss_account).first()
            if job is None:
                raise ValidationError({"job": "职位不属于当前 BOSS 账号"})
        idempotency_key = f"workflow-run:{version.pk}:{request_id}"
        existed = WorkflowRun.objects.filter(idempotency_key=idempotency_key).exists()
        run = create_run(
            version=version, actor=request.user, mode=mode, idempotency_key=idempotency_key,
            input_snapshot=request.data.get("input") if isinstance(request.data.get("input"), dict) else {}, job=job,
        )
        run = advance_run(run, executor=execute_workflow_node)
        return Response(WorkflowRunSerializer(run, context=self.get_serializer_context()).data, status=status.HTTP_200_OK if existed else status.HTTP_201_CREATED)


class WorkflowRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkflowRun.objects.select_related("version__template", "boss_account", "job", "actor").prefetch_related("node_runs", "events")
    serializer_class = WorkflowRunSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset if self.request.user.is_superuser else queryset.filter(boss_account__authorized_users=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        run = self.get_object()
        if run.status not in {WorkflowRun.Status.SUCCEEDED, WorkflowRun.Status.FAILED, WorkflowRun.Status.CANCELLED, WorkflowRun.Status.PAUSED}:
            run = advance_run(run, executor=execute_workflow_node)
        return Response(self.get_serializer(run).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return Response(self.get_serializer(pause_run(self.get_object(), actor=request.user)).data)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        run = resume_run(self.get_object(), actor=request.user)
        return Response(self.get_serializer(advance_run(run, executor=execute_workflow_node)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self.get_serializer(cancel_run(self.get_object(), actor=request.user)).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def decision(self, request, pk=None):
        run = self.get_object()
        node = run.node_runs.filter(pk=request.data.get("node_id")).first()
        if node is None:
            raise ValidationError({"node_id": "运行节点不存在"})
        if not isinstance(request.data.get("approved"), bool):
            raise ValidationError({"approved": "必须明确通过或跳过"})
        note = str(request.data.get("note", ""))[:500]
        approval_id = (node.output or {}).get("approval_id")
        if node.node_type in HUMAN_NODE_TYPES:
            decide_node(node, approved=request.data["approved"], actor=request.user, note=note)
        elif approval_id:
            if node.status != "waiting_human":
                raise WorkflowConflict("该执行节点当前不等待确认")
            approval = AutomationApproval.objects.select_for_update().filter(
                pk=approval_id,
                boss_account=run.boss_account,
            ).first()
            if approval is None:
                raise ValidationError({"node_id": "执行节点确认快照不存在"})
            if request.data["approved"]:
                try:
                    approval = approve(approval=approval, actor=request.user)
                except ValidationError:
                    approval.refresh_from_db()
                    if approval.status == AutomationApproval.Status.EXPIRED:
                        return Response({"detail": "该确认项已过期"}, status=status.HTTP_400_BAD_REQUEST)
                    raise
                if approval.action in {
                    AutomationApproval.Action.GREET,
                    AutomationApproval.Action.REQUEST_RESUME,
                    AutomationApproval.Action.SEND_INTERVIEW,
                }:
                    materialize_communication_batch(approval=approval, actor=request.user)
                elif approval.action == AutomationApproval.Action.SEARCH_AND_PULL_RESUMES:
                    campaign = SearchCampaign.objects.filter(
                        pk=approval.payload.get("campaign_id"),
                        boss_account=approval.boss_account,
                    ).first()
                    if campaign is None:
                        raise ValidationError("主动寻访任务不存在")
                    start_search_campaign(campaign=campaign, actor=request.user, approval=approval)
                elif approval.action == AutomationApproval.Action.DEEP_MATCH:
                    _materialize_deep_match_task(
                        approval=approval,
                        actor=request.user,
                        workflow_node_run=node,
                    )
                else:
                    raise ValidationError("该流程执行确认类型不受支持")
            else:
                reject(approval=approval, actor=request.user, note=note)
                decide_node(node, approved=False, actor=request.user, note=note)
        else:
            raise WorkflowConflict("该节点等待外部事件，不能人工标记完成")
        return Response(self.get_serializer(advance_run(run, executor=execute_workflow_node)).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        run = self.get_object()
        node = run.node_runs.filter(pk=request.data.get("node_id")).first()
        if node is None:
            raise ValidationError({"node_id": "运行节点不存在"})
        retry_node(node, actor=request.user)
        return Response(self.get_serializer(advance_run(run, executor=execute_workflow_node)).data)


class SearchCampaignViewSet(viewsets.ModelViewSet):
    queryset = SearchCampaign.objects.select_related("boss_account", "job", "created_by")
    serializer_class = SearchCampaignSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        return super().get_queryset().filter(job__in=accessible_jobs(self.request.user)).distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        campaign = self.get_object()
        if campaign.status not in {SearchCampaign.Status.DRAFT, SearchCampaign.Status.CANCELLED, SearchCampaign.Status.FAILED}:
            raise ValidationError("运行中或已完成的主动寻访记录需要保留审计，不可删除")
        campaign.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        campaign = self.get_object()
        approval = prepare_search_campaign(campaign=campaign, actor=request.user)
        return Response({
            "campaign": self.get_serializer(campaign).data,
            "approval_id": str(approval.pk),
            "approval_status": approval.status,
            "resume_view_budget": approval.item_count,
        })

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        return Response(self.get_serializer(stop_search_campaign(campaign=self.get_object())).data)


class ResumeViewSet(ArchivableViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Resume.objects.select_related("candidate", "application__job").prefetch_related(
        "structured_versions", "ai_tasks"
    ).all()
    serializer_class = ResumeSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(application__job__in=accessible_jobs(self.request.user))
        job = requested_open_job(self.request)
        if job:
            queryset = queryset.filter(application__job=job)
        return queryset.distinct()

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        resume = self.get_object()
        if not resume.file or not resume.file.storage.exists(resume.file.name):
            return Response({"detail": "简历文件不可用"}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(resume.file.open("rb"), content_type=resume.content_type or "application/octet-stream")
        response["Content-Disposition"] = content_disposition_header(
            as_attachment=request.query_params.get("download") == "1",
            filename=resume.original_name,
        )
        response["X-Frame-Options"] = "SAMEORIGIN"
        RecruitmentAuditLog.objects.create(
            actor=request.user,
            boss_account=resume.application.job.boss_account if resume.application_id else None,
            action="resume_downloaded" if request.query_params.get("download") == "1" else "resume_previewed",
            target_id=str(resume.pk),
            detail={"candidate_id": resume.candidate_id, "version": resume.version},
        )
        return response

    @action(detail=True, methods=["post"], url_path="retry-structure")
    def retry_structure(self, request, pk=None):
        resume = self.get_object()
        task = resume.ai_tasks.filter(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status__in=[AiProcessingTask.Status.FAILED, AiProcessingTask.Status.WAITING_CONFIG],
        ).order_by("-created_at").first()
        try:
            if task:
                task = retry_ai_task(task=task, requested_by=request.user)
                created = False
            else:
                task, created = enqueue_resume_structure(
                    resume=resume, requested_by=request.user, request_id=request.data.get("request_id") or None
                )
        except (PermissionError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            AiProcessingTaskSerializer(task).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class StructuredResumeVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StructuredResumeVersion.objects.select_related(
        "resume__candidate", "resume__application__job", "extraction"
    )
    serializer_class = StructuredResumeVersionSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(resume__application__job__in=accessible_jobs(self.request.user))
        job_id = self.request.query_params.get("job")
        resume_id = self.request.query_params.get("resume")
        if job_id:
            queryset = queryset.filter(resume__application__job_id=job_id)
        if resume_id:
            queryset = queryset.filter(resume_id=resume_id)
        return queryset.distinct()


class ResumeAssessmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ResumeAssessment.objects.select_related(
        "structured_resume__resume__candidate",
        "structured_resume__resume__application__job",
        "standard",
    )
    serializer_class = ResumeAssessmentSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(
            structured_resume__resume__application__job__in=accessible_jobs(self.request.user)
        )
        job_id = self.request.query_params.get("job")
        resume_id = self.request.query_params.get("resume")
        if job_id:
            queryset = queryset.filter(standard__job_id=job_id)
        if resume_id:
            queryset = queryset.filter(structured_resume__resume_id=resume_id)
        return queryset.distinct()

    @action(detail=False, methods=["post"])
    def score(self, request):
        try:
            request_id = uuid.UUID(str(request.data.get("request_id")))
        except (TypeError, ValueError, AttributeError):
            raise ValidationError({"request_id": "请输入有效的请求标识"})
        try:
            job_id = int(request.data.get("job"))
        except (TypeError, ValueError):
            raise ValidationError({"job": "请选择职位"})
        resume_ids = request.data.get("resume_ids")
        if not isinstance(resume_ids, list) or not resume_ids:
            raise ValidationError({"resume_ids": "请至少选择一份简历"})

        job = accessible_jobs(request.user).filter(pk=job_id).first()
        if not job:
            raise NotFound("职位不存在")
        standard = job.standard_versions.filter(status=JobStandardVersion.Status.PUBLISHED).first()
        if not standard:
            return Response(
                {"detail": "请先确认评分标准", "code": "standard_not_published"},
                status=status.HTTP_409_CONFLICT,
            )

        resumes = {
            resume.pk: resume
            for resume in Resume.objects.filter(
                pk__in=resume_ids,
                application__job=job,
                archived_at__isnull=True,
            ).prefetch_related("structured_versions")
        }
        results = []
        for raw_resume_id in resume_ids:
            try:
                resume_id = int(raw_resume_id)
            except (TypeError, ValueError):
                resume_id = raw_resume_id
            resume = resumes.get(resume_id)
            structured = resume.structured_versions.order_by("-version").first() if resume else None
            if not structured:
                results.append(
                    {
                        "resume_id": resume_id,
                        "code": "resume_not_ready",
                        "detail": "简历不存在、未归属当前职位或尚未完成结构化",
                    }
                )
                continue
            task, _created = enqueue_resume_score(
                structured_resume=structured,
                standard=standard,
                requested_by=request.user,
                request_id=request_id,
            )
            results.append({"resume_id": resume.pk, "task_id": str(task.pk), "status": task.status})
        return Response({"request_id": str(request_id), "results": results}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def rescore(self, request, pk=None):
        assessment = self.get_object()
        try:
            request_id = uuid.UUID(str(request.data.get("request_id")))
        except (TypeError, ValueError, AttributeError):
            raise ValidationError({"request_id": "请输入有效的请求标识"})
        current_standard = JobStandardVersion.objects.filter(
            job=assessment.standard.job, status=JobStandardVersion.Status.PUBLISHED
        ).first()
        if not current_standard:
            raise ValidationError({"standard": "当前职位没有已启用的评分标准"})
        task, created = enqueue_resume_score(
            structured_resume=assessment.structured_resume,
            standard=current_standard,
            requested_by=request.user,
            request_id=request_id,
        )
        return Response(
            AiProcessingTaskSerializer(task).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AiProcessingTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AiProcessingTask.objects.select_related("job", "resume", "standard", "requested_by")
    serializer_class = AiProcessingTaskSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset().filter(job__in=accessible_jobs(self.request.user))
        for field in ("job", "kind", "status", "resume"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset.distinct()

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        try:
            task = retry_ai_task(task=self.get_object(), requested_by=request.user)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(task).data)


class RpaTaskViewSet(ArchivableViewSetMixin, viewsets.ModelViewSet):
    queryset = RpaTask.objects.select_related("boss_account", "created_by", "worker").prefetch_related("events")
    serializer_class = RpaTaskSerializer
    permission_classes = [RecruitmentWritePermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(boss_account__authorized_users=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        response_status = status.HTTP_200_OK if getattr(serializer.instance, "_was_existing", False) else status.HTTP_201_CREATED
        return Response(serializer.data, status=response_status, headers=headers)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, pk=None):
        task = self.get_object()
        if task.action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
            if task.status != RpaTask.Status.PENDING:
                raise ValidationError("当前主动寻访任务不能通过通用取消入口处理")
            campaign = SearchCampaign.objects.filter(
                pk=task.request_payload.get("campaign_id"),
                boss_account=task.boss_account,
            ).first()
            if campaign is None:
                raise ValidationError("主动寻访任务缺少有效 campaign，无法安全取消")
            stop_search_campaign(campaign=campaign)
            task.refresh_from_db()
        else:
            task = cancel_task(task=task, actor=request.user)
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        task = retry_task(task=self.get_object(), actor=request.user)
        return Response(self.get_serializer(task).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    return Response(build_recruitment_dashboard(request.user))


@api_view(["GET", "POST", "DELETE"])
@permission_classes([RecruitmentWritePermission])
def demo_data_view(request):
    if request.method == "GET":
        return Response(demo_status())
    if request.method == "POST":
        load_demo_data(request.user)
        return Response(demo_status(), status=status.HTTP_201_CREATED)
    return Response(clear_demo_data())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def automation_summary_view(request):
    tasks = RpaTask.objects.all()
    if not request.user.is_superuser:
        tasks = tasks.filter(boss_account__authorized_users=request.user)
    counts = {row["status"]: row["count"] for row in tasks.values("status").annotate(count=Count("id"))}
    worker = RpaWorker.objects.order_by("-last_seen_at").first()
    worker_data = None
    if worker:
        worker_data = {
            "key": worker.key,
            "hostname": worker.hostname,
            "version": worker.version,
            "status": worker.status,
            "last_seen_at": worker.last_seen_at,
        }
    active_statuses = [RpaTask.Status.PENDING, RpaTask.Status.LEASED, RpaTask.Status.RUNNING]
    return Response({
        "worker": worker_data,
        "cli_available": bool(worker and worker.capabilities.get("boss_cli")),
        "task_counts": counts,
        "has_active_task": tasks.filter(status__in=active_statuses).exists(),
    })
