from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob, RpaTask, RpaWorker
from .permissions import RecruitmentWritePermission
from .rpa.tasks import cancel_task, retry_task
from .serializers import BossAccountSerializer, CandidateSerializer, JobApplicationSerializer, RecruitmentJobSerializer, RpaTaskSerializer


class BossAccountViewSet(viewsets.ModelViewSet):
    queryset = BossAccount.objects.all().order_by("name")
    serializer_class = BossAccountSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(authorized_users=self.request.user)

    def perform_create(self, serializer):
        account = serializer.save()
        account.authorized_users.add(self.request.user)


class RecruitmentJobViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentJob.objects.select_related("boss_account", "owner").all().order_by("-updated_at")
    serializer_class = RecruitmentJobSerializer
    permission_classes = [RecruitmentWritePermission]


class CandidateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Candidate.objects.all().order_by("-updated_at")
    serializer_class = CandidateSerializer
    permission_classes = [RecruitmentWritePermission]


class JobApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobApplication.objects.select_related("candidate", "job", "owner").all().order_by("-updated_at")
    serializer_class = JobApplicationSerializer
    permission_classes = [RecruitmentWritePermission]


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
