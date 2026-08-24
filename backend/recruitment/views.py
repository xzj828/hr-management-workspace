from dataclasses import asdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .demo_data import clear_demo_data, demo_status, load_demo_data
from .models import (
    AutomationApproval,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    JobApplication,
    RecruitmentJob,
    Resume,
    RpaTask,
    RpaWorker,
)
from .permissions import RecruitmentWritePermission
from .rpa.tasks import cancel_task, create_task, retry_task
from .serializers import (
    BossAccountSerializer,
    AutomationApprovalSerializer,
    CandidateDiscoveryImportSerializer,
    CandidateDiscoverySearchSerializer,
    CandidateDiscoverySerializer,
    CandidateSerializer,
    DeepMatchPrepareSerializer,
    JobApplicationSerializer,
    PositionSyncRequestSerializer,
    RecruitmentJobSerializer,
    ResumeSerializer,
    RpaTaskSerializer,
)
from .services.approvals import approve
from .services.discovery import import_discoveries


class BossAccountViewSet(viewsets.ModelViewSet):
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


class RecruitmentJobViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentJob.objects.select_related("boss_account", "owner").annotate(
        candidate_count=Count("applications", distinct=True)
    ).order_by("-updated_at")
    serializer_class = RecruitmentJobSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
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


class CandidateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Candidate.objects.prefetch_related(
        "applications__job", "applications__owner", "resumes"
    ).annotate(resume_count=Count("resumes", distinct=True)).order_by("-updated_at")
    serializer_class = CandidateSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(current_title__icontains=search)
                | Q(current_city__icontains=search)
            )
        if self.request.query_params.get("job"):
            queryset = queryset.filter(applications__job_id=self.request.query_params["job"])
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
        queryset = super().get_queryset()
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
        response = AutomationApprovalSerializer(approval).data
        if task:
            response["task_id"] = str(task.pk)
            response["task_status"] = task.status
        return Response(response, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class JobApplicationViewSet(viewsets.ModelViewSet):
    queryset = JobApplication.objects.select_related(
        "candidate", "job", "owner"
    ).prefetch_related("candidate__resumes").order_by("-updated_at")
    serializer_class = JobApplicationSerializer
    permission_classes = [RecruitmentWritePermission]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("job"):
            queryset = queryset.filter(job_id=self.request.query_params["job"])
        if self.request.query_params.get("stage"):
            queryset = queryset.filter(stage=self.request.query_params["stage"])
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset


class ResumeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Resume.objects.select_related("candidate", "application__job").all()
    serializer_class = ResumeSerializer
    permission_classes = [RecruitmentWritePermission]

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
        return response


class RpaTaskViewSet(viewsets.ModelViewSet):
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
    terminal = [JobApplication.Stage.HIRED, JobApplication.Stage.REJECTED, JobApplication.Stage.TALENT_POOL]
    return Response({
        "open_jobs": RecruitmentJob.objects.filter(status=RecruitmentJob.Status.OPEN).count(),
        "active_candidates": JobApplication.objects.exclude(stage__in=terminal).count(),
        "waiting_resumes": JobApplication.objects.filter(stage=JobApplication.Stage.WAITING_RESUME).count(),
        "waiting_interviews": JobApplication.objects.filter(stage=JobApplication.Stage.TO_INTERVIEW).count(),
        "boss_accounts_ready": BossAccount.objects.filter(status=BossAccount.Status.READY, active=True).count(),
    })


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
