from django.db.models import Q

from recruitment.models import RecruitmentJob


def accessible_jobs(user):
    queryset = RecruitmentJob.objects.all()
    if user.is_superuser:
        return queryset
    return queryset.filter(
        Q(boss_account__authorized_users=user)
        | Q(boss_account__isnull=True, owner=user)
    ).distinct()
