from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob
from .permissions import RecruitmentWritePermission
from .serializers import BossAccountSerializer, CandidateSerializer, JobApplicationSerializer, RecruitmentJobSerializer


class BossAccountViewSet(viewsets.ModelViewSet):
    queryset = BossAccount.objects.all().order_by("name")
    serializer_class = BossAccountSerializer
    permission_classes = [RecruitmentWritePermission]


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
