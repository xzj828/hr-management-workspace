import uuid

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q


class BossAccount(models.Model):
    class BrowserType(models.TextChoices):
        CHROME = "chrome", "Chrome"
        EDGE = "edge", "Edge"

    class LoginStatus(models.TextChoices):
        UNKNOWN = "unknown", "未检查"
        BROWSER_STOPPED = "browser_stopped", "浏览器未启动"
        WAITING_LOGIN = "waiting_login", "等待登录"
        WAITING_HUMAN = "waiting_human", "等待人工验证"
        READY = "ready", "已登录"
        ERROR = "error", "异常"

    class Status(models.TextChoices):
        OFFLINE = "offline", "离线"
        READY = "ready", "可用"
        RUNNING = "running", "执行中"
        PAUSED = "paused", "已暂停"
        RISK = "risk", "风控"

    name = models.CharField(max_length=100, unique=True)
    browser_profile = models.SlugField(max_length=80, unique=True)
    cdp_port = models.PositiveIntegerField(unique=True)
    browser_type = models.CharField(max_length=16, choices=BrowserType.choices, default=BrowserType.CHROME)
    browser_executable = models.CharField(max_length=500, blank=True)
    user_data_dir = models.CharField(max_length=500, blank=True)
    login_status = models.CharField(max_length=32, choices=LoginStatus.choices, default=LoginStatus.UNKNOWN)
    verification_status = models.CharField(max_length=40, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
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


class RpaWorker(models.Model):
    class Status(models.TextChoices):
        ONLINE = "online", "在线"
        OFFLINE = "offline", "离线"

    key = models.SlugField(max_length=100, unique=True)
    hostname = models.CharField(max_length=255)
    version = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OFFLINE)
    capabilities = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RpaTask(models.Model):
    class Action(models.TextChoices):
        CHECK_STATUS = "check_status", "检查状态"
        SYNC_POSITIONS = "sync_positions", "同步职位"

    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        LEASED = "leased", "已领取"
        RUNNING = "running", "执行中"
        WAITING_HUMAN = "waiting_human", "等待人工处理"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    boss_account = models.ForeignKey(BossAccount, on_delete=models.CASCADE, related_name="rpa_tasks")
    action = models.CharField(max_length=32, choices=Action.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_rpa_tasks")
    worker = models.ForeignKey(RpaWorker, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    request_payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["boss_account"],
                condition=Q(status__in=["pending", "leased", "running"]),
                name="unique_active_rpa_task_per_account",
            )
        ]


class RpaTaskEvent(models.Model):
    task = models.ForeignKey(RpaTask, on_delete=models.CASCADE, related_name="events")
    level = models.CharField(max_length=16, default="info")
    event = models.CharField(max_length=64)
    message = models.CharField(max_length=500)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class RecruitmentAuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="recruitment_audits")
    boss_account = models.ForeignKey(BossAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=80)
    target_id = models.CharField(max_length=100, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
