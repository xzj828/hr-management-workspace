from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AccountProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "系统管理员"
        HR = "hr", "HR"
        SUPERVISOR = "supervisor", "部门主管"
        VIEWER = "viewer", "只读"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="account_profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    department = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.user.username} / {self.get_role_display()}"


class EmployeeTag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=20, default="#64748B")
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AttendancePolicy(models.Model):
    class Mode(models.TextChoices):
        STANDARD = "standard", "标准考勤"
        FLEXIBLE = "flexible", "弹性工作"
        EXEMPT = "exempt", "免考勤"
        PART_TIME = "part_time", "兼职"
        SHIFT = "shift", "轮班"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.STANDARD)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    grace_minutes = models.PositiveIntegerField(default=0)
    cross_day_cutoff_minutes = models.PositiveIntegerField(
        default=180,
        validators=[MinValueValidator(0), MaxValueValidator(720)],
        help_text="凌晨多少分钟内的单条打卡需要进入跨日疑似队列",
    )
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    class EmploymentStatus(models.TextChoices):
        PROBATION = "probation", "试用期"
        REGULAR = "regular", "已转正"
        FOUNDER = "founder", "创始人"
        PART_TIME = "part_time", "兼职"
        LEFT = "left", "已离职"

    employee_no = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    aliases = models.JSONField(default=list, blank=True)
    department = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=100, blank=True)
    join_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(
        max_length=20,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.REGULAR,
    )
    active = models.BooleanField(default=True)
    attendance_policy = models.ForeignKey(
        AttendancePolicy,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employees",
    )
    expected_days_override = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tags = models.ManyToManyField(EmployeeTag, blank=True, related_name="employees")

    phone = models.CharField(max_length=30, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_holder = models.CharField(max_length=80, blank=True)
    bank_province = models.CharField(max_length=80, blank=True)
    bank_branch = models.CharField(max_length=200, blank=True)
    bank_card_number = models.CharField(max_length=80, blank=True)
    alipay_account = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department", "employee_no"]

    def __str__(self):
        return f"{self.employee_no} {self.name}"


def import_upload_path(instance, filename):
    return f"attendance_imports/{instance.year}/{instance.month:02d}/{filename}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待处理"
        PROCESSING = "processing", "处理中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    original_filename = models.CharField(max_length=255)
    source_file = models.FileField(upload_to=import_upload_path)
    file_sha256 = models.CharField(max_length=64)
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    default_expected_days = models.DecimalField(max_digits=5, decimal_places=2, default=25)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    matched_rows = models.PositiveIntegerField(default=0)
    unmatched_rows = models.PositiveIntegerField(default=0)
    suspicion_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="attendance_imports")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.year}-{self.month:02d} {self.original_filename}"


class RawPunchDay(models.Model):
    class MatchStatus(models.TextChoices):
        EMPLOYEE_NO = "employee_no", "工号匹配"
        NAME = "name", "姓名匹配"
        ALIAS = "alias", "别名匹配"
        UNMATCHED = "unmatched", "未匹配"

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="raw_days")
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="raw_days")
    source_row = models.PositiveIntegerField()
    employee_no = models.CharField(max_length=40, blank=True)
    source_name = models.CharField(max_length=100)
    organization = models.CharField(max_length=120, blank=True)
    attendance_rule = models.CharField(max_length=120, blank=True)
    work_date = models.DateField()
    raw_value = models.TextField(blank=True)
    punches = models.JSONField(default=list, blank=True)
    has_punch = models.BooleanField(default=False)
    effective_has_punch = models.BooleanField(default=False)
    match_status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.UNMATCHED)
    is_cross_day_suspicion = models.BooleanField(default=False)

    class Meta:
        ordering = ["source_row", "work_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "source_row", "work_date"],
                name="unique_source_row_work_date",
            )
        ]


class AttendanceResult(models.Model):
    class Status(models.TextChoices):
        NORMAL = "normal", "正常"
        REVIEW = "review", "需要复核"
        APPROVED = "approved", "已确认"

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="results")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance_results")
    punch_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    due_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    rest_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    leave_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    adjustment_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    adjustment_hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    actual_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    late_count = models.PositiveIntegerField(default=0)
    absence_count = models.PositiveIntegerField(default=0)
    missing_punch_count = models.PositiveIntegerField(default=0)
    deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REVIEW)
    note = models.TextField(blank=True)
    rule_trace = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__department", "employee__employee_no"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "employee"], name="unique_batch_employee_result")
        ]


class CrossDaySuspicion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待审核"
        ASSIGN_PREVIOUS = "assign_previous", "归入前一天"
        KEEP_CURRENT = "keep_current", "保留当天"

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="suspicions")
    raw_day = models.OneToOneField(RawPunchDay, on_delete=models.CASCADE, related_name="cross_day_review")
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    previous_date = models.DateField()
    work_date = models.DateField()
    punch_text = models.CharField(max_length=50)
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

