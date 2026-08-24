from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from recruitment.models import (
    ApplicationStageHistory,
    BossAccount,
    InterviewInvitation,
    JobApplication,
    RecruitmentJob,
    Resume,
    RpaTask,
)


TERMINAL_STAGES = {
    JobApplication.Stage.HIRED,
    JobApplication.Stage.REJECTED,
    JobApplication.Stage.TALENT_POOL,
}

FUNNEL_GROUPS = [
    ("new", "新候选人", [JobApplication.Stage.NEW, JobApplication.Stage.TO_CONTACT]),
    ("communicating", "沟通中", [JobApplication.Stage.GREETED, JobApplication.Stage.COMMUNICATING, JobApplication.Stage.WAITING_RESUME]),
    ("resume", "简历筛选", [JobApplication.Stage.RESUME_RECEIVED, JobApplication.Stage.TO_SCREEN]),
    ("interview", "面试", [JobApplication.Stage.TO_INTERVIEW, JobApplication.Stage.INTERVIEWING]),
    ("offer", "Offer", [JobApplication.Stage.TO_OFFER]),
    ("hired", "已录用", [JobApplication.Stage.HIRED]),
]


def _scope(user):
    if user.is_superuser:
        accounts = BossAccount.objects.filter(active=True)
        jobs = RecruitmentJob.objects.all()
    else:
        accounts = BossAccount.objects.filter(active=True, authorized_users=user).distinct()
        jobs = RecruitmentJob.objects.filter(
            Q(boss_account__authorized_users=user) | Q(boss_account__isnull=True, owner=user)
        ).distinct()
    applications = JobApplication.objects.filter(job__in=jobs)
    tasks = RpaTask.objects.filter(boss_account__in=accounts)
    return accounts, jobs, applications, tasks


def build_recruitment_dashboard(user):
    accounts, jobs, applications, tasks = _scope(user)
    today = timezone.localdate()
    metrics = {
        "open_jobs": jobs.filter(status=RecruitmentJob.Status.OPEN).count(),
        "active_candidates": applications.exclude(stage__in=TERMINAL_STAGES).count(),
        "waiting_resumes": applications.filter(stage=JobApplication.Stage.WAITING_RESUME).count(),
        "waiting_interviews": applications.filter(stage=JobApplication.Stage.TO_INTERVIEW).count(),
        "boss_accounts_ready": accounts.filter(status=BossAccount.Status.READY).count(),
    }

    action_specs = [
        ("to_contact", "待联系候选人", applications.filter(stage__in=[JobApplication.Stage.NEW, JobApplication.Stage.TO_CONTACT]).count(), "/recruitment/candidates?stage=to_contact"),
        ("to_screen", "待筛选简历", applications.filter(stage__in=[JobApplication.Stage.RESUME_RECEIVED, JobApplication.Stage.TO_SCREEN]).count(), "/recruitment/resumes"),
        ("to_interview", "待安排面试", metrics["waiting_interviews"], "/recruitment/pipeline?stage=to_interview"),
        ("waiting_human", "待人工处理", tasks.filter(status=RpaTask.Status.WAITING_HUMAN).count(), "/recruitment/automation"),
    ]
    today_actions = [
        {"key": key, "label": label, "count": count, "route": route, "priority": "high" if count else "normal"}
        for key, label, count, route in action_specs
    ]

    alerts = []
    for account in accounts.exclude(status=BossAccount.Status.READY).order_by("name")[:6]:
        alerts.append({
            "key": f"account-{account.pk}",
            "severity": "high" if account.status == BossAccount.Status.RISK else "medium",
            "title": f"{account.name} 需要处理",
            "detail": account.get_login_status_display(),
            "route": "/recruitment/automation",
            "action_label": "查看账号",
        })
    failed_today = tasks.filter(status=RpaTask.Status.FAILED, completed_at__date=today).count()
    if failed_today:
        alerts.append({
            "key": "failed-tasks", "severity": "high", "title": f"今日 {failed_today} 个自动化任务失败",
            "detail": "查看错误原因后决定是否重试", "route": "/recruitment/automation", "action_label": "查看任务",
        })
    waiting_human = tasks.filter(status=RpaTask.Status.WAITING_HUMAN).count()
    if waiting_human:
        alerts.append({
            "key": "waiting-human", "severity": "medium", "title": f"{waiting_human} 个任务等待人工处理",
            "detail": "可能需要登录、扫码或安全验证", "route": "/recruitment/automation", "action_label": "立即处理",
        })

    stage_counts = {row["stage"]: row["count"] for row in applications.values("stage").annotate(count=Count("id"))}
    funnel = [
        {"key": key, "label": label, "count": sum(stage_counts.get(stage, 0) for stage in stages)}
        for key, label, stages in FUNNEL_GROUPS
    ]

    interview_stages = [
        JobApplication.Stage.TO_INTERVIEW,
        JobApplication.Stage.INTERVIEWING,
        JobApplication.Stage.TO_OFFER,
        JobApplication.Stage.HIRED,
    ]
    job_rows = jobs.filter(status=RecruitmentJob.Status.OPEN).annotate(
        candidate_total=Count("applications", distinct=True),
        interview_total=Count("applications", filter=Q(applications__stage__in=interview_stages), distinct=True),
        hired_total=Count("applications", filter=Q(applications__stage=JobApplication.Stage.HIRED), distinct=True),
    ).order_by("-updated_at", "id")[:8]
    job_progress = [{
        "id": job.pk,
        "title": job.title,
        "headcount": job.headcount,
        "candidates": job.candidate_total,
        "interviews": job.interview_total,
        "hired": job.hired_total,
        "completion": min(100, round(job.hired_total * 100 / max(job.headcount, 1))),
        "route": f"/recruitment/jobs?job={job.pk}",
    } for job in job_rows]

    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_applications = applications.filter(created_at__date=day)
        day_resumes = Resume.objects.filter(application__in=applications, acquired_at__date=day)
        day_interviews = InterviewInvitation.objects.filter(action__application__in=applications, interview_at__date=day)
        day_hires = ApplicationStageHistory.objects.filter(
            application__in=applications, to_stage=JobApplication.Stage.HIRED, created_at__date=day,
        )
        trend.append({
            "date": day.isoformat(),
            "label": f"{day.month}/{day.day}",
            "candidates": day_applications.count(),
            "resumes": day_resumes.count(),
            "interviews": day_interviews.count(),
            "hires": day_hires.count(),
        })

    recent_tasks = [{
        "id": str(task.pk),
        "account_name": task.boss_account.name,
        "action": task.action,
        "action_label": task.get_action_display(),
        "status": task.status,
        "status_label": task.get_status_display(),
        "created_at": task.created_at,
        "error_message": task.error_message,
        "route": "/recruitment/automation",
    } for task in tasks.select_related("boss_account").order_by("-created_at")[:8]]

    return {
        "metrics": metrics,
        "today_actions": today_actions,
        "alerts": alerts,
        "funnel": funnel,
        "job_progress": job_progress,
        "trend": trend,
        "recent_tasks": recent_tasks,
    }
