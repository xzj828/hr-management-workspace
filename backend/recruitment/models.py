import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


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
    daily_search_limit = models.PositiveIntegerField(default=100)
    daily_resume_view_limit = models.PositiveIntegerField(default=20)
    daily_message_limit = models.PositiveIntegerField(default=50)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    authorized_users = models.ManyToManyField(User, blank=True, related_name="boss_accounts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RecruitmentJob(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "招聘中"
        PAUSED = "paused", "已暂停"
        CLOSED = "closed", "已关闭"

    boss_account = models.ForeignKey(
        BossAccount,
        on_delete=models.PROTECT,
        related_name="jobs",
        null=True,
        blank=True,
    )
    external_id = models.CharField(max_length=120)
    title = models.CharField(max_length=120)
    department = models.CharField(max_length=100, blank=True)
    jd = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recruitment_jobs")
    headcount = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    is_demo = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
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
    is_demo = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
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
    is_demo = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["candidate", "job"], name="unique_candidate_job_application")
        ]


class Resume(models.Model):
    class Source(models.TextChoices):
        BOSS = "boss", "BOSS 直聘"
        BOSS_ONLINE = "boss_online", "BOSS 在线简历"
        UPLOAD = "upload", "人工上传"
        DEMO = "demo", "演示数据"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "待处理"
        READY = "ready", "待 AI 评估"
        ERROR = "error", "文件不可用"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="resumes")
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.SET_NULL,
        related_name="resumes",
        null=True,
        blank=True,
    )
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="recruitment/resumes/%Y/%m")
    content_type = models.CharField(max_length=100, default="application/pdf")
    file_size = models.PositiveBigIntegerField(default=0)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.BOSS)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.READY,
    )
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    version = models.PositiveIntegerField(default=1)
    external_id = models.CharField(max_length=160, blank=True)
    acquired_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "sha256"],
                condition=~Q(sha256=""),
                name="unique_candidate_resume_hash",
            ),
            models.UniqueConstraint(
                fields=["candidate", "version"],
                name="unique_candidate_resume_version",
            ),
        ]


class CandidateDiscovery(models.Model):
    class Source(models.TextChoices):
        RECOMMEND = "recommend", "推荐候选人"
        SEARCH = "search", "常规搜索"
        DEEP_SEARCH = "deep_search", "深度搜索"

    class IdentityQuality(models.TextChoices):
        PLATFORM = "platform", "平台标识"
        FINGERPRINT = "fingerprint", "组合指纹"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    boss_account = models.ForeignKey(
        BossAccount,
        on_delete=models.CASCADE,
        related_name="candidate_discoveries",
    )
    job = models.ForeignKey(
        RecruitmentJob,
        on_delete=models.CASCADE,
        related_name="candidate_discoveries",
    )
    source = models.CharField(max_length=24, choices=Source.choices)
    external_id = models.CharField(max_length=160, blank=True)
    fingerprint = models.CharField(max_length=64)
    identity_quality = models.CharField(max_length=20, choices=IdentityQuality.choices)
    display_name = models.CharField(max_length=100)
    current_title = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80, blank=True)
    experience = models.CharField(max_length=160, blank=True)
    education = models.CharField(max_length=160, blank=True)
    advantage = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    criteria = models.JSONField(default=dict, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    contact_hint = models.CharField(max_length=40, blank=True)
    imported_candidate = models.ForeignKey(
        Candidate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discovery_sources",
    )
    expires_at = models.DateTimeField()
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["boss_account", "job", "fingerprint"],
                name="unique_account_job_discovery_fingerprint",
            )
        ]


class CandidateExternalIdentity(models.Model):
    boss_account = models.ForeignKey(
        BossAccount,
        on_delete=models.CASCADE,
        related_name="candidate_identities",
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="external_identities",
    )
    external_id = models.CharField(max_length=160, blank=True)
    fingerprint = models.CharField(max_length=64)
    identity_quality = models.CharField(
        max_length=20,
        choices=CandidateDiscovery.IdentityQuality.choices,
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["boss_account", "fingerprint"],
                name="unique_account_candidate_fingerprint",
            )
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
        RECOMMEND_CANDIDATES = "recommend_candidates", "推荐候选人"
        SEARCH_CANDIDATES = "search_candidates", "搜索候选人"
        GREET = "greet", "打招呼"
        REQUEST_RESUME = "request_resume", "索要简历"
        VIEW_ONLINE_RESUME = "view_online_resume", "查看在线简历"
        SEND_INTERVIEW = "send_interview", "发送面试邀约"
        DEEP_MATCH = "deep_match", "深度匹配"
        SYNC_CONVERSATIONS = "sync_conversations", "同步沟通状态"
        SEARCH_AND_PULL_RESUMES = "search_pull_resumes", "搜索并拉取在线简历"

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
    approval = models.ForeignKey(
        "AutomationApproval",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rpa_tasks",
    )
    execution_batch = models.ForeignKey(
        "ExecutionBatch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rpa_tasks",
    )
    workflow_node_run = models.ForeignKey(
        "WorkflowNodeRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rpa_tasks",
    )
    idempotency_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["boss_account"],
                condition=Q(status__in=["leased", "running"]),
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


class AutomationApproval(models.Model):
    class Action(models.TextChoices):
        SYNC_POSITIONS = "sync_positions", "同步职位"
        GREET = "greet", "打招呼"
        REQUEST_RESUME = "request_resume", "索要简历"
        VIEW_ONLINE_RESUME = "view_online_resume", "查看在线简历"
        SEND_INTERVIEW = "send_interview", "发送面试邀约"
        DEEP_MATCH = "deep_match", "深度匹配"

    class Status(models.TextChoices):
        DRAFT = "draft", "待确认"
        APPROVED = "approved", "已确认"
        REJECTED = "rejected", "已拒绝"
        EXPIRED = "expired", "已过期"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    action = models.CharField(max_length=40, choices=Action.choices)
    boss_account = models.ForeignKey(
        BossAccount,
        on_delete=models.PROTECT,
        related_name="automation_approvals",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_automation_approvals",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_automation_approvals",
    )
    payload = models.JSONField(default=dict)
    item_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    expires_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ExecutionBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        RUNNING = "running", "执行中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        PARTIAL = "partial", "部分完成"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval = models.OneToOneField(
        AutomationApproval,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="batch",
    )
    boss_account = models.ForeignKey(
        BossAccount,
        on_delete=models.PROTECT,
        related_name="execution_batches",
    )
    action = models.CharField(max_length=40)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_execution_batches",
    )
    workflow_node_run = models.OneToOneField(
        "WorkflowNodeRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execution_batch",
    )
    total_items = models.PositiveIntegerField(default=1)
    succeeded_items = models.PositiveIntegerField(default=0)
    failed_items = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class StepExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        LEASED = "leased", "已领取"
        RUNNING = "running", "执行中"
        VERIFYING = "verifying", "核验中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "已跳过"
        CANCELLED = "cancelled", "已取消"

    batch = models.ForeignKey(ExecutionBatch, on_delete=models.CASCADE, related_name="steps")
    target_key = models.CharField(max_length=160)
    target_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    attempt = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "target_key"], name="unique_batch_target")
        ]


class AutomationEvidence(models.Model):
    step = models.ForeignKey(StepExecution, on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=32)
    summary = models.CharField(max_length=300)
    metadata = models.JSONField(default=dict, blank=True)
    file = models.FileField(upload_to="recruitment/evidence/%Y/%m", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class AutomationUsage(models.Model):
    class Metric(models.TextChoices):
        SEARCH = "search", "候选人搜索"
        DEEP_MATCH = "deep_match", "深度匹配"
        RESUME_VIEW = "resume_view", "在线简历查看"
        CONTACT = "contact", "打招呼"
        MESSAGE = "message", "发送消息"

    boss_account = models.ForeignKey(
        BossAccount,
        on_delete=models.CASCADE,
        related_name="automation_usage",
    )
    day = models.DateField()
    metric = models.CharField(max_length=24, choices=Metric.choices)
    used = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["boss_account", "day", "metric"],
                name="unique_daily_automation_usage",
            )
        ]


class ConversationAction(models.Model):
    class Action(models.TextChoices):
        GREET = "greet", "打招呼"
        REQUEST_RESUME = "request_resume", "索要简历"
        SEND_INTERVIEW = "send_interview", "发送面试邀约"

    class Status(models.TextChoices):
        DRAFT = "draft", "待确认"
        APPROVED = "approved", "已确认"
        PENDING = "pending", "待执行"
        RUNNING = "running", "执行中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "已跳过"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, related_name="conversation_actions")
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="conversation_actions")
    action = models.CharField(max_length=32, choices=Action.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    message_snapshot = models.TextField()
    target_snapshot = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=180, unique=True)
    approval = models.ForeignKey(
        AutomationApproval, on_delete=models.PROTECT, null=True, blank=True, related_name="conversation_actions"
    )
    batch = models.ForeignKey(
        ExecutionBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="conversation_actions"
    )
    step = models.OneToOneField(
        StepExecution, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversation_action"
    )
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_conversation_actions")
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class InterviewInvitation(models.Model):
    class Mode(models.TextChoices):
        ONLINE = "online", "线上面试"
        OFFLINE = "offline", "线下面试"

    action = models.OneToOneField(ConversationAction, on_delete=models.CASCADE, related_name="interview_invitation")
    interview_at = models.DateTimeField()
    mode = models.CharField(max_length=16, choices=Mode.choices)
    location = models.CharField(max_length=500)
    contact_name = models.CharField(max_length=100)
    note = models.TextField(blank=True)


class ConversationSyncState(models.Model):
    application = models.OneToOneField(JobApplication, on_delete=models.CASCADE, related_name="conversation_state")
    boss_account = models.ForeignKey(BossAccount, on_delete=models.CASCADE, related_name="conversation_states")
    cursor = models.CharField(max_length=300, blank=True)
    last_message_preview = models.CharField(max_length=500, blank=True)
    has_candidate_reply = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class JobRequirementDocument(models.Model):
    class Category(models.TextChoices):
        REQUIREMENT = "requirement", "岗位需求"
        PERSONA = "persona", "候选人画像"
        OTHER = "other", "其他补充"

    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, related_name="requirement_documents")
    category = models.CharField(max_length=24, choices=Category.choices)
    title = models.CharField(max_length=160)
    current_version = models.ForeignKey(
        "JobRequirementDocumentVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_documents",
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="job_requirement_documents")
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "title", "id"]


class JobRequirementDocumentVersion(models.Model):
    document = models.ForeignKey(JobRequirementDocument, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="recruitment/job-documents/%Y/%m")
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="job_requirement_document_versions")
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["document", "version"], name="unique_job_document_version"),
            models.UniqueConstraint(fields=["document", "sha256"], name="unique_job_document_hash"),
        ]


class MessageSyncPolicy(models.Model):
    boss_account = models.OneToOneField(BossAccount, on_delete=models.CASCADE, related_name="message_sync_policy")
    enabled = models.BooleanField(default=True)
    interval_minutes = models.PositiveIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
    )
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ConversationMessage(models.Model):
    class Direction(models.TextChoices):
        CANDIDATE = "candidate", "候选人"
        HR = "hr", "HR"
        SYSTEM = "system", "系统"

    conversation_state = models.ForeignKey(
        ConversationSyncState,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    external_id = models.CharField(max_length=200, blank=True)
    fingerprint = models.CharField(max_length=64)
    direction = models.CharField(max_length=16, choices=Direction.choices)
    content = models.TextField(blank=True)
    sent_at = models.DateTimeField()
    raw_payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sent_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation_state", "external_id"],
                condition=~Q(external_id=""),
                name="unique_conversation_external_message",
            ),
            models.UniqueConstraint(
                fields=["conversation_state", "fingerprint"],
                name="unique_conversation_message_fingerprint",
            ),
        ]


class MessageAttachment(models.Model):
    message = models.ForeignKey(ConversationMessage, on_delete=models.CASCADE, related_name="attachments")
    external_id = models.CharField(max_length=200, blank=True)
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="recruitment/message-attachments/%Y/%m", blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    source_payload = models.JSONField(default=dict, blank=True)
    archived_resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="message_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "external_id"],
                condition=~Q(external_id=""),
                name="unique_message_external_attachment",
            ),
            models.UniqueConstraint(
                fields=["message", "sha256"],
                condition=~Q(sha256=""),
                name="unique_message_attachment_hash",
            ),
        ]


class HumanAttention(models.Model):
    class Type(models.TextChoices):
        OBSERVING_CANDIDATE = "observing_candidate", "候选人观望"
        GREETING_REQUIRED = "greeting_required", "待人工打招呼"
        ACCOUNT_LOGIN = "account_login", "账号需要登录"
        RISK_CONTROL = "risk_control", "验证码或风控"
        IDENTITY_AMBIGUOUS = "identity_ambiguous", "候选人身份歧义"
        RESUME_REQUEST_FAILED = "resume_request_failed", "求简历失败"
        ARCHIVE_FAILED = "archive_failed", "简历归档失败"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        OPEN = "open", "待处理"
        RESOLVED = "resolved", "已处理"
        ARCHIVED = "archived", "已归档"

    attention_type = models.CharField(max_length=40, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    title = models.CharField(max_length=200)
    detail = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=220, unique=True)
    priority = models.PositiveSmallIntegerField(default=0)
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="human_attentions")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, null=True, blank=True, related_name="human_attentions")
    application = models.ForeignKey(JobApplication, on_delete=models.PROTECT, null=True, blank=True, related_name="human_attentions")
    workflow_run = models.ForeignKey("WorkflowRun", on_delete=models.PROTECT, null=True, blank=True, related_name="human_attentions")
    workflow_node_run = models.ForeignKey("WorkflowNodeRun", on_delete=models.PROTECT, null=True, blank=True, related_name="human_attentions")
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_human_attentions")
    resolution_note = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "created_at", "id"]


class SearchCampaign(models.Model):
    class Source(models.TextChoices):
        RECOMMEND = "recommend", "推荐"
        SEARCH = "search", "常规搜索"
        DEEP_SEARCH = "deep_search", "深度搜索"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        QUEUED = "queued", "已排队"
        RUNNING = "running", "运行中"
        PAUSED = "paused", "已暂停"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    class StopReason(models.TextChoices):
        NONE = "", "未停止"
        TARGET_REACHED = "target_reached", "达到拉取数量"
        SCAN_LIMIT = "scan_limit", "达到扫描上限"
        QUOTA = "quota", "查看额度不足"
        PAYWALL = "paywall", "遇到付费墙"
        RISK_CONTROL = "risk_control", "验证码或风控"
        ACCOUNT_OFFLINE = "account_offline", "账号离线"
        USER_STOPPED = "user_stopped", "人工停止"
        ERROR = "error", "执行异常"

    name = models.CharField(max_length=160)
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="search_campaigns")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, related_name="search_campaigns")
    workflow_run = models.ForeignKey("WorkflowRun", on_delete=models.PROTECT, null=True, blank=True, related_name="search_campaigns")
    source = models.CharField(max_length=24, choices=Source.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    target_resume_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    max_scan_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    scanned_count = models.PositiveIntegerField(default=0)
    pulled_resume_count = models.PositiveIntegerField(default=0)
    criteria = models.JSONField(default=dict, blank=True)
    stop_reason = models.CharField(max_length=32, choices=StopReason.choices, default=StopReason.NONE, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="search_campaigns")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class ApplicationStageHistory(models.Model):
    class Source(models.TextChoices):
        AUTOMATION = "automation", "自动化"
        MANUAL = "manual", "人工调整"

    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, related_name="stage_history")
    from_stage = models.CharField(max_length=30, choices=JobApplication.Stage.choices)
    to_stage = models.CharField(max_length=30, choices=JobApplication.Stage.choices)
    source = models.CharField(max_length=20, choices=Source.choices)
    reason = models.CharField(max_length=500)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="stage_changes")
    task = models.ForeignKey(RpaTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="stage_changes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class WorkflowTemplate(models.Model):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="workflow_templates")
    active_version = models.ForeignKey(
        "WorkflowVersion", on_delete=models.SET_NULL, null=True, blank=True, related_name="active_for_templates"
    )
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WorkflowVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ENABLED = "enabled", "已启用"
        DISABLED = "disabled", "已停用"

    template = models.ForeignKey(WorkflowTemplate, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_versions")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="workflow_versions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["template", "version"], name="unique_workflow_version")]


class WorkflowNode(models.Model):
    version = models.ForeignKey(WorkflowVersion, on_delete=models.CASCADE, related_name="nodes")
    node_key = models.CharField(max_length=80)
    node_type = models.CharField(max_length=40)
    label = models.CharField(max_length=120, blank=True)
    position = models.JSONField(default=dict)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "node_key"], name="unique_workflow_node_key")]


class WorkflowEdge(models.Model):
    version = models.ForeignKey(WorkflowVersion, on_delete=models.CASCADE, related_name="edges")
    source = models.ForeignKey(WorkflowNode, on_delete=models.CASCADE, related_name="outgoing_edges")
    target = models.ForeignKey(WorkflowNode, on_delete=models.CASCADE, related_name="incoming_edges")
    order = models.PositiveIntegerField(default=0)
    condition = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "source", "target"], name="unique_workflow_edge")]
        ordering = ["order", "id"]


class WorkflowRun(models.Model):
    class Mode(models.TextChoices):
        DRY_RUN = "dry_run", "试运行"
        FORMAL = "formal", "正式运行"

    class Status(models.TextChoices):
        QUEUED = "queued", "已排队"
        RUNNING = "running", "运行中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        PAUSED = "paused", "已暂停"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(WorkflowVersion, on_delete=models.PROTECT, related_name="runs")
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="workflow_runs")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_runs")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="workflow_runs")
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.DRY_RUN)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED, db_index=True)
    idempotency_key = models.CharField(max_length=180, unique=True)
    graph_snapshot = models.JSONField(default=dict)
    input_snapshot = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class WorkflowNodeRun(models.Model):
    class Status(models.TextChoices):
        BLOCKED = "blocked", "等待前置"
        READY = "ready", "就绪"
        RUNNING = "running", "运行中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "已跳过"
        CANCELLED = "cancelled", "已取消"

    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="node_runs")
    node_key = models.CharField(max_length=80)
    node_type = models.CharField(max_length=40)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.BLOCKED, db_index=True)
    config_snapshot = models.JSONField(default=dict, blank=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    attempt = models.PositiveSmallIntegerField(default=0)
    idempotency_key = models.CharField(max_length=200, unique=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["run", "node_key"], name="unique_workflow_run_node_key")]


class WorkflowRunEvent(models.Model):
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="events")
    node_run = models.ForeignKey(WorkflowNodeRun, on_delete=models.CASCADE, null=True, blank=True, related_name="events")
    level = models.CharField(max_length=16, default="info")
    event = models.CharField(max_length=64)
    message = models.CharField(max_length=500)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class FileTextExtraction(models.Model):
    class SourceKind(models.TextChoices):
        JOB_DOCUMENT = "job_document", "岗位文档"
        RESUME = "resume", "简历"

    class Method(models.TextChoices):
        DOCX = "docx", "DOCX"
        DOC_CONVERT = "doc_convert", "DOC 转换"
        PDF_TEXT = "pdf_text", "PDF 文字"
        PDF_OCR = "pdf_ocr", "PDF OCR"
        IMAGE_OCR = "image_ocr", "图片 OCR"

    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        READY = "ready", "已完成"
        FAILED = "failed", "失败"

    source_kind = models.CharField(max_length=24, choices=SourceKind.choices)
    source_id = models.PositiveBigIntegerField()
    source_sha256 = models.CharField(max_length=64)
    method = models.CharField(max_length=24, choices=Method.choices)
    plain_text = models.TextField(blank=True)
    blocks = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_kind", "source_id", "source_sha256"],
                name="unique_file_text_extraction_source",
            )
        ]


class JobStandardVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已启用"
        SUPERSEDED = "superseded", "历史版本"

    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, related_name="standard_versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    source_document_versions = models.ManyToManyField(
        JobRequirementDocumentVersion,
        related_name="job_standard_versions",
        blank=True,
    )
    criteria = models.JSONField(default=dict, blank=True)
    unresolved_questions = models.JSONField(default=list, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=40, default="job-standard-v1")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_job_standards")
    published_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_job_standards",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["job", "version"], name="unique_job_standard_version"),
            models.UniqueConstraint(
                fields=["job"],
                condition=Q(status="published"),
                name="unique_published_standard_per_job",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and original.status == self.Status.PUBLISHED:
                protected = (
                    "status",
                    "criteria",
                    "unresolved_questions",
                    "model_name",
                    "prompt_version",
                    "published_by_id",
                    "published_at",
                )
                if any(getattr(original, field) != getattr(self, field) for field in protected):
                    raise ValidationError("已启用的评分标准不可直接修改，请创建新草稿")
        return super().save(*args, **kwargs)


class StructuredResumeVersion(models.Model):
    resume = models.ForeignKey(Resume, on_delete=models.PROTECT, related_name="structured_versions")
    version = models.PositiveIntegerField()
    extraction = models.ForeignKey(FileTextExtraction, on_delete=models.PROTECT, related_name="structured_resumes")
    data = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    model_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=40, default="resume-structure-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["resume", "version"], name="unique_structured_resume_version")
        ]


class ResumeAssessment(models.Model):
    class Recommendation(models.TextChoices):
        ADVANCE = "advance", "建议进一步沟通"
        REVIEW = "review", "建议人工复核"
        HOLD = "hold", "暂不建议推进"

    structured_resume = models.ForeignKey(
        StructuredResumeVersion,
        on_delete=models.PROTECT,
        related_name="assessments",
    )
    standard = models.ForeignKey(JobStandardVersion, on_delete=models.PROTECT, related_name="assessments")
    total_score = models.DecimalField(max_digits=5, decimal_places=2)
    dimension_scores = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    gaps = models.JSONField(default=list, blank=True)
    verification_questions = models.JSONField(default=list, blank=True)
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    recommendation = models.CharField(max_length=32, choices=Recommendation.choices)
    model_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=40, default="resume-score-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["structured_resume", "standard"],
                name="unique_resume_assessment_inputs",
            )
        ]


class AiProcessingTask(models.Model):
    class Kind(models.TextChoices):
        JOB_STANDARD = "job_standard", "岗位标准"
        RESUME_STRUCTURE = "resume_structure", "简历结构化"
        RESUME_SCORE = "resume_score", "简历评分"

    class Status(models.TextChoices):
        WAITING_CONFIG = "waiting_config", "等待模型配置"
        PENDING = "pending", "等待处理"
        EXTRACTING = "extracting", "文本提取中"
        OCR = "ocr", "OCR 处理中"
        MODEL = "model", "模型处理中"
        WAITING_REVIEW = "waiting_review", "待人工确认"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True)
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="ai_processing_tasks")
    job = models.ForeignKey(
        RecruitmentJob,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ai_tasks",
    )
    document_version = models.ForeignKey(
        JobRequirementDocumentVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ai_tasks",
    )
    resume = models.ForeignKey(
        Resume,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ai_tasks",
    )
    standard = models.ForeignKey(
        JobStandardVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ai_tasks",
    )
    idempotency_key = models.CharField(max_length=160, unique=True)
    progress = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    leased_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    result_ref = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["available_at", "created_at"]
