from rest_framework import serializers

from .models import (
    AccountProfile,
    AttendancePolicy,
    AttendanceResult,
    CrossDaySuspicion,
    Employee,
    EmployeeTag,
    ImportBatch,
    RawPunchDay,
)
from .permissions import is_hr_user


def mask_value(value, visible=4):
    if not value:
        return ""
    value = str(value)
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


class AccountSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()

    class Meta:
        from django.contrib.auth.models import User

        model = User
        fields = ["id", "username", "first_name", "role", "role_label", "is_superuser"]

    def get_role(self, obj):
        if obj.is_superuser:
            return AccountProfile.Role.ADMIN
        profile, _ = AccountProfile.objects.get_or_create(user=obj)
        return profile.role

    def get_role_label(self, obj):
        if obj.is_superuser:
            return AccountProfile.Role.ADMIN.label
        profile, _ = AccountProfile.objects.get_or_create(user=obj)
        return profile.get_role_display()


class EmployeeTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeTag
        fields = ["id", "name", "color", "description"]


class AttendancePolicySerializer(serializers.ModelSerializer):
    mode_label = serializers.CharField(source="get_mode_display", read_only=True)
    employee_count = serializers.IntegerField(source="employees.count", read_only=True)

    class Meta:
        model = AttendancePolicy
        fields = [
            "id",
            "code",
            "name",
            "mode",
            "mode_label",
            "start_time",
            "end_time",
            "grace_minutes",
            "cross_day_cutoff_minutes",
            "description",
            "active",
            "employee_count",
        ]


class EmployeeSerializer(serializers.ModelSerializer):
    attendance_policy = AttendancePolicySerializer(read_only=True)
    attendance_policy_id = serializers.PrimaryKeyRelatedField(
        source="attendance_policy",
        queryset=AttendancePolicy.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    tags = EmployeeTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        source="tags",
        queryset=EmployeeTag.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )
    employment_status_label = serializers.CharField(source="get_employment_status_display", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_no",
            "name",
            "aliases",
            "department",
            "position",
            "join_date",
            "employment_status",
            "employment_status_label",
            "active",
            "attendance_policy",
            "attendance_policy_id",
            "expected_days_override",
            "tags",
            "tag_ids",
            "phone",
            "bank_name",
            "bank_account_holder",
            "bank_province",
            "bank_branch",
            "bank_card_number",
            "alipay_account",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not request or not is_hr_user(request.user):
            data["phone"] = mask_value(data.get("phone"), 4)
            data["bank_card_number"] = mask_value(data.get("bank_card_number"), 4)
            data["alipay_account"] = mask_value(data.get("alipay_account"), 3)
            data["bank_branch"] = ""
        return data


class ImportBatchSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    uploaded_by_name = serializers.CharField(source="uploaded_by.username", read_only=True)
    pending_suspicions = serializers.SerializerMethodField()

    class Meta:
        model = ImportBatch
        fields = [
            "id",
            "original_filename",
            "year",
            "month",
            "default_expected_days",
            "status",
            "status_label",
            "total_rows",
            "matched_rows",
            "unmatched_rows",
            "suspicion_count",
            "pending_suspicions",
            "error_message",
            "uploaded_by_name",
            "created_at",
            "completed_at",
        ]

    def get_pending_suspicions(self, obj):
        return obj.suspicions.filter(status=CrossDaySuspicion.Status.PENDING).count()


class AttendanceEmployeeSerializer(serializers.ModelSerializer):
    policy_mode = serializers.CharField(source="attendance_policy.mode", read_only=True, default="standard")
    policy_name = serializers.CharField(source="attendance_policy.name", read_only=True, default="未设置")

    class Meta:
        model = Employee
        fields = ["id", "employee_no", "name", "department", "position", "policy_mode", "policy_name"]


class AttendanceResultSerializer(serializers.ModelSerializer):
    employee = AttendanceEmployeeSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AttendanceResult
        fields = [
            "id",
            "batch",
            "employee",
            "punch_days",
            "due_days",
            "rest_days",
            "leave_days",
            "overtime_days",
            "overtime_hours",
            "adjustment_days",
            "adjustment_hours",
            "actual_days",
            "late_count",
            "absence_count",
            "missing_punch_count",
            "deduction",
            "status",
            "status_label",
            "note",
            "rule_trace",
            "reviewed_at",
            "updated_at",
        ]
        read_only_fields = [
            "batch",
            "employee",
            "punch_days",
            "due_days",
            "rest_days",
            "actual_days",
            "status",
            "rule_trace",
            "reviewed_at",
            "updated_at",
        ]


class RawPunchDaySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True, default=None)
    match_status_label = serializers.CharField(source="get_match_status_display", read_only=True)

    class Meta:
        model = RawPunchDay
        fields = [
            "id",
            "batch",
            "employee",
            "employee_name",
            "employee_no",
            "source_name",
            "organization",
            "work_date",
            "raw_value",
            "punches",
            "has_punch",
            "effective_has_punch",
            "match_status",
            "match_status_label",
            "is_cross_day_suspicion",
        ]


class CrossDaySuspicionSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True, default="未匹配")
    employee_no = serializers.CharField(source="employee.employee_no", read_only=True, default="")
    department = serializers.CharField(source="employee.department", read_only=True, default="")
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    source_name = serializers.CharField(source="raw_day.source_name", read_only=True)
    previous_raw_value = serializers.SerializerMethodField()

    class Meta:
        model = CrossDaySuspicion
        fields = [
            "id",
            "batch",
            "employee",
            "employee_name",
            "employee_no",
            "department",
            "source_name",
            "previous_date",
            "previous_raw_value",
            "work_date",
            "punch_text",
            "reason",
            "status",
            "status_label",
            "reviewed_at",
            "created_at",
        ]

    def get_previous_raw_value(self, obj):
        previous = RawPunchDay.objects.filter(
            batch=obj.batch,
            source_row=obj.raw_day.source_row,
            work_date=obj.previous_date,
        ).first()
        return previous.raw_value if previous else ""
