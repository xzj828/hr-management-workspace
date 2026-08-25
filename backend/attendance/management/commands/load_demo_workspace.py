import calendar
import hashlib
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from openpyxl import Workbook

from attendance.models import (
    AttendancePolicy,
    AttendanceResult,
    CrossDaySuspicion,
    Employee,
    EmployeeTag,
    ImportBatch,
)
from attendance.services import process_import_batch, recalculate_result, resolve_cross_day
from recruitment.demo_data import clear_demo_data, demo_status, load_demo_data


DEMO_EMPLOYEE_PREFIX = "DEMO-"
DEMO_ATTENDANCE_PREFIX = "演示考勤-"


EMPLOYEES = [
    {
        "employee_no": "DEMO-001",
        "name": "林知夏",
        "aliases": ["知夏"],
        "department": "产品中心",
        "position": "产品经理",
        "policy": "standard",
        "status": Employee.EmploymentStatus.PROBATION,
        "tags": ["演示数据", "新员工"],
        "phone": "13800000001",
    },
    {
        "employee_no": "DEMO-002",
        "name": "周启明",
        "aliases": ["启明"],
        "department": "研发中心",
        "position": "前端工程师",
        "policy": "standard",
        "status": Employee.EmploymentStatus.REGULAR,
        "tags": ["演示数据"],
        "phone": "13800000002",
    },
    {
        "employee_no": "DEMO-003",
        "name": "苏晚",
        "aliases": [],
        "department": "研发中心",
        "position": "UX 设计师",
        "policy": "standard",
        "status": Employee.EmploymentStatus.REGULAR,
        "tags": ["演示数据"],
        "phone": "13800000003",
    },
    {
        "employee_no": "DEMO-004",
        "name": "陈墨",
        "aliases": [],
        "department": "客户成功部",
        "position": "实施顾问",
        "policy": "flexible",
        "status": Employee.EmploymentStatus.REGULAR,
        "tags": ["演示数据"],
        "phone": "13800000004",
    },
    {
        "employee_no": "DEMO-005",
        "name": "何安",
        "aliases": [],
        "department": "研发中心",
        "position": "后端工程师",
        "policy": "standard",
        "status": Employee.EmploymentStatus.REGULAR,
        "tags": ["演示数据"],
        "phone": "13800000005",
    },
    {
        "employee_no": "DEMO-006",
        "name": "宋怡",
        "aliases": [],
        "department": "客户成功部",
        "position": "客户成功经理",
        "policy": "exempt",
        "status": Employee.EmploymentStatus.REGULAR,
        "tags": ["演示数据", "领导层"],
        "phone": "13800000006",
    },
    {
        "employee_no": "DEMO-007",
        "name": "高远",
        "aliases": [],
        "department": "人力资源部",
        "position": "HRBP",
        "policy": "standard",
        "status": Employee.EmploymentStatus.REGULAR,
        "tags": ["演示数据"],
        "phone": "13800000007",
    },
    {
        "employee_no": "DEMO-008",
        "name": "唐可",
        "aliases": [],
        "department": "研发中心",
        "position": "研发实习生",
        "policy": "part_time",
        "status": Employee.EmploymentStatus.PART_TIME,
        "tags": ["演示数据", "新员工", "兼职"],
        "phone": "13800000008",
    },
]


class Command(BaseCommand):
    help = "向项目原有招聘与考勤模型加载可识别、可重复清理的演示数据"

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="只清理本命令创建的演示数据，不加载新数据",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            attendance_counts = self._clear_attendance_demo(remove_employees=True)
            recruitment_counts = demo_status()["counts"]
            clear_demo_data()
            self.stdout.write(
                self.style.SUCCESS(
                    "演示数据已清理："
                    f"考勤批次 {attendance_counts['batches']}，"
                    f"员工 {attendance_counts['employees']}，"
                    f"招聘职位 {recruitment_counts['jobs']}"
                )
            )
            return

        username = options["admin_username"]
        user = get_user_model().objects.filter(
            username=username,
            is_active=True,
            is_staff=True,
        ).first()
        if not user:
            raise CommandError(
                f"找不到可用的后台管理员账号：{username}，请先运行 setup_system"
            )

        self._assert_demo_only_attendance_database()

        policies = {
            policy.code: policy
            for policy in AttendancePolicy.objects.filter(
                code__in={employee["policy"] for employee in EMPLOYEES}
            )
        }
        missing_policies = sorted(
            {employee["policy"] for employee in EMPLOYEES} - policies.keys()
        )
        if missing_policies:
            raise CommandError(
                f"缺少考勤策略：{', '.join(missing_policies)}，请先运行 setup_system"
            )

        previous_batches = list(
            ImportBatch.objects.filter(
                original_filename__startswith=DEMO_ATTENDANCE_PREFIX
            )
        )
        employees = self._upsert_employees(policies)
        batches = []
        try:
            batches = self._load_attendance_batches(user, employees)
            recruitment_counts = load_demo_data(user)
        except Exception:
            self._delete_attendance_batches(batches)
            raise
        self._delete_attendance_batches(previous_batches)

        result_count = AttendanceResult.objects.filter(batch__in=batches).count()
        pending_count = CrossDaySuspicion.objects.filter(
            batch__in=batches,
            status=CrossDaySuspicion.Status.PENDING,
        ).count()
        self.stdout.write(
            self.style.SUCCESS(
                "演示数据已加载："
                f"员工 {len(employees)}，考勤批次 {len(batches)}，"
                f"考勤结果 {result_count}，待审跨日 {pending_count}，"
                f"招聘职位 {recruitment_counts['jobs']}，"
                f"候选人 {recruitment_counts['candidates']}"
            )
        )

    @staticmethod
    def _assert_demo_only_attendance_database():
        real_employee_count = Employee.objects.exclude(
            employee_no__startswith=DEMO_EMPLOYEE_PREFIX
        ).count()
        real_batch_count = ImportBatch.objects.exclude(
            original_filename__startswith=DEMO_ATTENDANCE_PREFIX
        ).count()
        expected_employee_numbers = {
            definition["employee_no"] for definition in EMPLOYEES
        }
        stale_demo_numbers = set(
            Employee.objects.filter(
                employee_no__startswith=DEMO_EMPLOYEE_PREFIX
            ).values_list("employee_no", flat=True)
        ) - expected_employee_numbers
        if real_employee_count or real_batch_count or stale_demo_numbers:
            raise CommandError(
                "检测到非演示考勤数据，已拒绝混合加载。"
                "请仅在空白演示数据库执行本命令；若是旧版演示数据，请先执行 --clear。"
            )

    def _clear_attendance_demo(self, *, remove_employees):
        batches = list(
            ImportBatch.objects.filter(original_filename__startswith=DEMO_ATTENDANCE_PREFIX)
        )
        self._delete_attendance_batches(batches)

        employee_count = 0
        if remove_employees:
            demo_employees = Employee.objects.filter(
                employee_no__startswith=DEMO_EMPLOYEE_PREFIX
            )
            employee_count = demo_employees.count()
            demo_employees.delete()
            EmployeeTag.objects.filter(name="演示数据", employees__isnull=True).delete()
        return {"batches": len(batches), "employees": employee_count}

    def _delete_attendance_batches(self, batches):
        batches = list(batches)
        storage = ImportBatch._meta.get_field("source_file").storage
        file_names = [batch.source_file.name for batch in batches if batch.source_file]
        batch_ids = [batch.pk for batch in batches if batch.pk]
        if batch_ids:
            ImportBatch.objects.filter(pk__in=batch_ids).delete()
        for file_name in file_names:
            try:
                storage.delete(file_name)
            except Exception as exc:
                self.stderr.write(
                    self.style.WARNING(f"演示源文件清理失败：{file_name}（{exc}）")
                )

    def _upsert_employees(self, policies):
        tag_definitions = [
            ("演示数据", "#087F73", "由 load_demo_workspace 创建的虚构演示人员"),
            ("新员工", "#2B8CB8", "入职初期人员"),
            ("兼职", "#D58A25", "非全日制或临时人员"),
            ("领导层", "#7C6FD1", "组织管理与决策岗位"),
        ]
        tag_map = {}
        for name, color, description in tag_definitions:
            tag, _ = EmployeeTag.objects.update_or_create(
                name=name,
                defaults={"color": color, "description": description},
            )
            tag_map[name] = tag
        today = timezone.localdate()
        join_dates = {
            "DEMO-001": today - timedelta(days=70),
            "DEMO-008": today - timedelta(days=50),
        }
        employees = []
        for definition in EMPLOYEES:
            employee, _ = Employee.objects.update_or_create(
                employee_no=definition["employee_no"],
                defaults={
                    "name": definition["name"],
                    "aliases": definition["aliases"],
                    "department": definition["department"],
                    "position": definition["position"],
                    "join_date": join_dates.get(
                        definition["employee_no"], today - timedelta(days=365)
                    ),
                    "employment_status": definition["status"],
                    "active": True,
                    "attendance_policy": policies[definition["policy"]],
                    "expected_days_override": None,
                    "phone": definition["phone"],
                    "bank_name": "",
                    "bank_account_holder": "",
                    "bank_province": "",
                    "bank_branch": "",
                    "bank_card_number": "",
                    "alipay_account": "",
                },
            )
            employee.tags.set([tag_map[name] for name in definition["tags"]])
            employees.append(employee)
        return employees

    def _load_attendance_batches(self, user, employees):
        today = timezone.localdate()
        current_start = today.replace(day=1)
        previous_end = current_start - timedelta(days=1)
        if today.day >= 8:
            periods = [
                (previous_end.year, previous_end.month, previous_end.day),
                (today.year, today.month, today.day),
            ]
        else:
            previous_start = previous_end.replace(day=1)
            older_end = previous_start - timedelta(days=1)
            periods = [
                (older_end.year, older_end.month, older_end.day),
                (previous_end.year, previous_end.month, previous_end.day),
            ]
        batches = []
        created_file_names = []
        try:
            for index, (year, month, last_day) in enumerate(periods):
                expected_days = sum(
                    date(year, month, day).weekday() < 5
                    for day in range(1, last_day + 1)
                )
                payload = self._build_workbook(year, month, last_day, employees)
                filename = f"{DEMO_ATTENDANCE_PREFIX}{year}-{month:02d}.xlsx"
                batch = ImportBatch(
                    original_filename=filename,
                    file_sha256=hashlib.sha256(payload).hexdigest(),
                    year=year,
                    month=month,
                    default_expected_days=Decimal(expected_days),
                    uploaded_by=user,
                )
                batch.source_file.save(filename, ContentFile(payload), save=False)
                created_file_names.append(batch.source_file.name)
                batch.save()
                batches.append(batch)
                process_import_batch(batch)
                self._enrich_results(batch, user, is_previous=index == 0)
            return batches
        except Exception:
            tracked_file_names = {
                batch.source_file.name for batch in batches if batch.source_file
            }
            self._delete_attendance_batches(batches)
            storage = ImportBatch._meta.get_field("source_file").storage
            for file_name in set(created_file_names) - tracked_file_names:
                try:
                    storage.delete(file_name)
                except Exception as exc:
                    self.stderr.write(
                        self.style.WARNING(
                            f"失败批次源文件清理失败：{file_name}（{exc}）"
                        )
                    )
            raise

    def _build_workbook(self, year, month, last_day, employees):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "飞书打卡"
        sheet.append(
            ["姓名", "组织名称", "工号", "考勤规则"]
            + [f"{day}日" for day in range(1, last_day + 1)]
        )
        suspicion_day = self._eligible_day(year, month, last_day, preferred=12)
        missing_day = self._eligible_day(
            year,
            month,
            last_day,
            preferred=18,
            excluded={suspicion_day - 1, suspicion_day},
        )
        policy_names = {policy.pk: policy.name for policy in AttendancePolicy.objects.all()}

        for employee in employees:
            values = []
            for day in range(1, last_day + 1):
                work_date = date(year, month, day)
                if work_date.weekday() >= 5:
                    values.append("-")
                elif employee.employee_no == "DEMO-002" and day == suspicion_day - 1:
                    values.append("13:36\n23:48")
                elif employee.employee_no == "DEMO-002" and day == suspicion_day:
                    values.append("01:16")
                elif employee.employee_no == "DEMO-005" and day == missing_day:
                    values.append("-")
                elif employee.employee_no == "DEMO-004" and day % 5 == 0:
                    values.append("10:18\n19:06")
                elif employee.employee_no == "DEMO-006" and day % 4 == 0:
                    values.append("-")
                elif employee.employee_no == "DEMO-003" and day % 6 == 0:
                    values.append("09:24\n19:32")
                else:
                    minute = (day + int(employee.employee_no[-1])) % 9
                    values.append(f"09:{minute:02d}\n18:{(12 + minute):02d}")
            sheet.append(
                [
                    employee.name,
                    employee.department,
                    employee.employee_no,
                    policy_names.get(employee.attendance_policy_id, ""),
                    *values,
                ]
            )

        unmatched_values = [
            "-"
            if date(year, month, day).weekday() >= 5
            else "09:05\n18:10"
            for day in range(1, last_day + 1)
        ]
        sheet.append(
            [
                "待建档人员（演示）",
                "外部协作",
                "UNMATCHED-DEMO",
                "标准考勤",
                *unmatched_values,
            ]
        )
        stream = BytesIO()
        workbook.save(stream)
        return stream.getvalue()

    @staticmethod
    def _eligible_day(year, month, last_day, *, preferred, excluded=None):
        excluded = excluded or set()
        max_day = min(last_day, calendar.monthrange(year, month)[1])
        candidates = sorted(
            (
                day
                for day in range(2, max_day + 1)
                if day not in excluded
                and date(year, month, day).weekday() in {1, 2, 3, 4}
            ),
            key=lambda day: (abs(day - min(preferred, max_day)), day),
        )
        if not candidates:
            raise CommandError(f"{year}-{month:02d} 没有足够的工作日生成演示数据")
        return candidates[0]

    def _enrich_results(self, batch, user, *, is_previous):
        designer = AttendanceResult.objects.get(
            batch=batch,
            employee__employee_no="DEMO-003",
        )
        designer.leave_days = Decimal("1")
        designer.overtime_days = Decimal("0.5")
        designer.overtime_hours = Decimal("4.5")
        designer.late_count = 1
        designer.note = "演示：含 1 天年假与一次加班记录"
        designer.save()

        missing = AttendanceResult.objects.get(
            batch=batch,
            employee__employee_no="DEMO-005",
        )
        missing.absence_count = 1
        missing.missing_punch_count = 1
        missing.deduction = Decimal("150")
        missing.note = "演示：有 1 天缺卡，等待 HR 复核"
        missing.save()

        if is_previous:
            suspicion = CrossDaySuspicion.objects.get(
                batch=batch,
                employee__employee_no="DEMO-002",
            )
            resolve_cross_day(
                suspicion,
                CrossDaySuspicion.Status.ASSIGN_PREVIOUS,
                user,
            )
            approved = AttendanceResult.objects.get(
                batch=batch,
                employee__employee_no="DEMO-002",
            )
            approved.adjustment_days = Decimal("1")
            approved.note = "演示：跨日打卡已归入前一天，并完成核算确认"
            recalculate_result(approved)
            approved.status = AttendanceResult.Status.APPROVED
            approved.reviewed_by = user
            approved.reviewed_at = timezone.now()
            approved.save()
