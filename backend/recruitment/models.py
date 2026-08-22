from django.contrib.auth.models import User
from django.db import models


class BossAccount(models.Model):
    class Status(models.TextChoices):
        OFFLINE = "offline", "离线"
        READY = "ready", "可用"
        RUNNING = "running", "执行中"
        PAUSED = "paused", "已暂停"
        RISK = "risk", "风控"

    name = models.CharField(max_length=100, unique=True)
    browser_profile = models.SlugField(max_length=80, unique=True)
    cdp_port = models.PositiveIntegerField(unique=True)
    daily_contact_limit = models.PositiveIntegerField(default=50)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    active = models.BooleanField(default=True)
    authorized_users = models.ManyToManyField(User, blank=True, related_name="boss_accounts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RecruitmentJob(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "招聘中"
        PAUSED = "paused", "已暂停"
        CLOSED = "closed", "已关闭"

    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="jobs")
    external_id = models.CharField(max_length=120)
    title = models.CharField(max_length=120)
    department = models.CharField(max_length=100, blank=True)
    jd = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recruitment_jobs")
    headcount = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["boss_account", "external_id"], name="unique_boss_job")
        ]


class Candidate(models.Model):
    identity_key = models.CharField(max_length=255, unique=True)
    external_id = models.CharField(max_length=120, blank=True)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    current_title = models.CharField(max_length=120, blank=True)
    current_city = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class JobApplication(models.Model):
    class Stage(models.TextChoices):
        NEW = "new", "新候选人"
        TO_CONTACT = "to_contact", "待联系"
        GREETED = "greeted", "已打招呼"
        COMMUNICATING = "communicating", "沟通中"
        WAITING_RESUME = "waiting_resume", "待简历"
        RESUME_RECEIVED = "resume_received", "已收简历"
        TO_SCREEN = "to_screen", "待筛选"
        TO_INTERVIEW = "to_interview", "待面试"
        INTERVIEWING = "interviewing", "面试中"
        TO_OFFER = "to_offer", "待 Offer"
        HIRED = "hired", "已录用"
        REJECTED = "rejected", "已淘汰"
        TALENT_POOL = "talent_pool", "人才库"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="applications")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, related_name="applications")
    source = models.CharField(max_length=30)
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.NEW)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="candidate_applications")
    priority = models.PositiveSmallIntegerField(default=0)
    last_interaction_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["candidate", "job"], name="unique_candidate_job_application")
        ]
