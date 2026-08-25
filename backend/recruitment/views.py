from dataclasses import asdict
from datetime import timedelta

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
    AutomationApproval,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    ConversationAction,
    ExecutionBatch,
    JobApplication,
    JobRequirementDocument,
    JobRequirementDocumentVersion,
    RecruitmentAuditLog,
    RecruitmentJob,
    Resume,
    RpaTask,
    RpaWorker,
    WorkflowTemplate,
    WorkflowVersion,
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
    PositionSyncRequestSerializer,
    RecruitmentJobSerializer,
    ResumeSerializer,
    RpaTaskSerializer,
    WorkflowTemplateSerializer,
    WorkflowVersionSerializer,
    WorkflowRunSerializer,
)
from .services.approvals import approve
from .services.access import accessible_jobs
from .services.communications import materialize_communication_batch, prepare_communication
from .services.communications import _identity_snapshot
from .services.discovery import import_discoveries
from .services.workflows import enable_version
from .services.account_status import apply_account_observation
from .services.dashboard import build_recruitment_dashboard
from .services.lifecycle import LifecycleConflict, archive_object, restore_object
from .services.job_documents import create_document, create_document_version, set_current_version
from .services.workflow_nodes import execute_workflow_node
from .services.workflow_runtime import advance_run, cancel_run, create_run, decide_node, pause_run, resume_run, retry_node


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
        approval = approve(approval=self.get_object(), actor=request.user)
        task = None
        created = False
        if approval.action == AutomationApproval.Action.DEEP_MATCH:
            payload = approval.payload
            task, created = create_task(
                account=approval.boss_account,
                action=RpaTask.Action.DEEP_MATCH,
                actor=request.user,
                approval=approval,
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
                return_created=True,
            )
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
                return_created=True,
            )
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
        approval, created = AutomationApproval.objects.get_or_create(
            idempotency_key=f"online-resume:{account.pk}:{request_id}",
            defaults={
                "action": AutomationApproval.Action.VIEW_ONLINE_RESUME,
                "boss_account": account,
                "created_by": request.user,
                "payload": {
                    "application_id": application.pk,
                    "target": _identity_snapshot(application, account),
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
    def decision(self, request, pk=None):
        run = self.get_object()
        node = run.node_runs.filter(pk=request.data.get("node_id")).first()
        if node is None:
            raise ValidationError({"node_id": "运行节点不存在"})
        if not isinstance(request.data.get("approved"), bool):
            raise ValidationError({"approved": "必须明确通过或跳过"})
        decide_node(node, approved=request.data["approved"], actor=request.user, note=str(request.data.get("note", ""))[:500])
        return Response(self.get_serializer(advance_run(run, executor=execute_workflow_node)).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        run = self.get_object()
        node = run.node_runs.filter(pk=request.data.get("node_id")).first()
        if node is None:
            raise ValidationError({"node_id": "运行节点不存在"})
        retry_node(node, actor=request.user)
        return Response(self.get_serializer(advance_run(run, executor=execute_workflow_node)).data)


class ResumeViewSet(ArchivableViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Resume.objects.select_related("candidate", "application__job").all()
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
        response = FileResponse(resume.file.open("rb"), content_type="application/pdf")
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
    def cancel(self, request, pk=None):
        task = cancel_task(task=self.get_object(), actor=request.user)
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
