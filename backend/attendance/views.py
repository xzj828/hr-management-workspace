import calendar
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db.models import Count, Q, Sum
from django.http import FileResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .exporter import build_summary_workbook
from .models import (
    AttendancePolicy,
    AttendanceResult,
    CrossDaySuspicion,
    Employee,
    EmployeeTag,
    ImportBatch,
    RawPunchDay,
)
from .permissions import HRPermission, HRWritePermission
from .serializers import (
    AccountSerializer,
    AttendancePolicySerializer,
    AttendanceResultSerializer,
    CrossDaySuspicionSerializer,
    EmployeeSerializer,
    EmployeeTagSerializer,
    ImportBatchSerializer,
    RawPunchDaySerializer,
)
from .services import file_sha256, process_import_batch, recalculate_result, resolve_cross_day


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_view(request):
    return Response({"detail": "CSRF cookie ready"})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"detail": "账号或密码错误"}, status=status.HTTP_400_BAD_REQUEST)
    if not user.is_active:
        return Response({"detail": "账号已停用"}, status=status.HTTP_403_FORBIDDEN)
    login(request, user)
    remember = bool(request.data.get("remember", False))
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember else 0)
    return Response(AccountSerializer(user).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    return Response(AccountSerializer(request.user).data)


class AttendancePolicyViewSet(viewsets.ModelViewSet):
    queryset = AttendancePolicy.objects.all()
    serializer_class = AttendancePolicySerializer
    permission_classes = [HRWritePermission]
    pagination_class = None


class EmployeeTagViewSet(viewsets.ModelViewSet):
    queryset = EmployeeTag.objects.all()
    serializer_class = EmployeeTagSerializer
    permission_classes = [HRWritePermission]
    pagination_class = None


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [HRWritePermission]

    def get_queryset(self):
        queryset = Employee.objects.select_related("attendance_policy").prefetch_related("tags")
        query = self.request.query_params.get("q")
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(employee_no__icontains=query)
                | Q(department__icontains=query)
                | Q(position__icontains=query)
            )
        active = self.request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(active=active == "true")
        mode = self.request.query_params.get("mode")
        if mode:
            queryset = queryset.filter(attendance_policy__mode=mode)
        tag = self.request.query_params.get("tag")
        if tag:
            queryset = queryset.filter(tags__id=tag)
        return queryset.distinct()


class ImportBatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ImportBatch.objects.select_related("uploaded_by")
    serializer_class = ImportBatchSerializer
    permission_classes = [HRPermission]
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "请选择打卡 Excel 文件"}, status=status.HTTP_400_BAD_REQUEST)
        if not uploaded_file.name.lower().endswith(".xlsx"):
            return Response({"detail": "第一版仅支持 .xlsx 文件"}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response({"detail": "文件不能超过 10MB"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            year = int(request.data.get("year"))
            month = int(request.data.get("month"))
            expected_days = Decimal(str(request.data.get("default_expected_days", "25")))
            if not 1 <= month <= 12:
                raise ValueError
        except (TypeError, ValueError, ArithmeticError):
            return Response({"detail": "年份、月份或默认应出勤天数无效"}, status=status.HTTP_400_BAD_REQUEST)

        digest = file_sha256(uploaded_file)
        duplicate = ImportBatch.objects.filter(file_sha256=digest, year=year, month=month).first()
        if duplicate:
            return Response(
                {
                    "detail": "同一个文件已导入过",
                    "batch": ImportBatchSerializer(duplicate).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        batch = ImportBatch.objects.create(
            original_filename=uploaded_file.name,
            source_file=uploaded_file,
            file_sha256=digest,
            year=year,
            month=month,
            default_expected_days=expected_days,
            uploaded_by=request.user,
        )
        try:
            process_import_batch(batch)
        except Exception as exc:
            return Response(
                ImportBatchSerializer(batch).data | {"detail": f"导入失败：{exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        batch = self.get_object()
        if batch.status != ImportBatch.Status.COMPLETED:
            return Response({"detail": "只有处理完成的批次可以导出"}, status=status.HTTP_400_BAD_REQUEST)
        stream = build_summary_workbook(batch)
        filename = f"{batch.year}.{batch.month}月考勤汇总.xlsx"
        return FileResponse(stream, as_attachment=True, filename=filename)


class AttendanceResultViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceResultSerializer
    permission_classes = [HRWritePermission]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = AttendanceResult.objects.select_related(
            "employee",
            "employee__attendance_policy",
            "batch",
        )
        batch_id = self.request.query_params.get("batch")
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        query = self.request.query_params.get("q")
        if query:
            queryset = queryset.filter(
                Q(employee__name__icontains=query)
                | Q(employee__employee_no__icontains=query)
                | Q(employee__department__icontains=query)
            )
        result_status = self.request.query_params.get("status")
        if result_status:
            queryset = queryset.filter(status=result_status)
        return queryset

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        instance = self.get_object()
        recalculate_result(instance)
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"], permission_classes=[HRPermission])
    def approve(self, request, pk=None):
        result = self.get_object()
        result.status = AttendanceResult.Status.APPROVED
        result.reviewed_by = request.user
        result.reviewed_at = timezone.now()
        result.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return Response(self.get_serializer(result).data)


class RawPunchDayViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RawPunchDaySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = RawPunchDay.objects.select_related("employee", "batch")
        for param, field in {
            "batch": "batch_id",
            "employee": "employee_id",
            "match_status": "match_status",
        }.items():
            value = self.request.query_params.get(param)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset


class CrossDaySuspicionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CrossDaySuspicionSerializer
    permission_classes = [HRPermission]

    def get_queryset(self):
        queryset = CrossDaySuspicion.objects.select_related("employee", "batch", "raw_day")
        batch_id = self.request.query_params.get("batch")
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        review_status = self.request.query_params.get("status")
        if review_status:
            queryset = queryset.filter(status=review_status)
        return queryset

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        suspicion = self.get_object()
        try:
            resolve_cross_day(suspicion, request.data.get("resolution"), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(suspicion).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    completed_batches = ImportBatch.objects.filter(status=ImportBatch.Status.COMPLETED).order_by(
        "-year", "-month", "-created_at"
    )
    latest_by_month = {}
    for item in completed_batches:
        latest_by_month.setdefault((item.year, item.month), item)
    available_batches = list(latest_by_month.values())
    available_periods = [
        {
            "value": f"{item.year:04d}-{item.month:02d}",
            "label": f"{item.year} 年 {item.month} 月",
            "batch_id": item.id,
        }
        for item in available_batches
    ]

    def parse_month(value):
        try:
            parsed = datetime.strptime(value, "%Y-%m")
        except (TypeError, ValueError):
            return None
        return parsed.year, parsed.month

    requested_from = request.query_params.get("from")
    requested_to = request.query_params.get("to")
    if requested_from or requested_to:
        start_period = parse_month(requested_from or requested_to)
        end_period = parse_month(requested_to or requested_from)
        if not start_period or not end_period:
            return Response({"detail": "日期格式应为 YYYY-MM"}, status=status.HTTP_400_BAD_REQUEST)
        if start_period > end_period:
            return Response({"detail": "起始月份不能晚于结束月份"}, status=status.HTTP_400_BAD_REQUEST)
    elif available_batches:
        start_period = end_period = (available_batches[0].year, available_batches[0].month)
    else:
        start_period = end_period = None

    selected_batches = []
    if start_period and end_period:
        selected_batches = [
            item
            for item in available_batches
            if start_period <= (item.year, item.month) <= end_period
        ]
        selected_batches.sort(key=lambda item: (item.year, item.month, item.created_at))

    period = {
        "from": f"{start_period[0]:04d}-{start_period[1]:02d}" if start_period else None,
        "to": f"{end_period[0]:04d}-{end_period[1]:02d}" if end_period else None,
        "batch_count": len(selected_batches),
    }
    if not selected_batches:
        return Response(
            {
                "batch": None,
                "batches": [],
                "period": period,
                "available_periods": available_periods,
                "selected_department": request.query_params.get("department", "").strip(),
                "available_departments": [],
                "kpis": {"employees": 0, "attendance_rate": 0, "review_count": 0, "pending_cross_day": 0},
                "summary": {"total_rows": 0, "matched_rows": 0, "unmatched_rows": 0, "suspicion_count": 0},
                "daily": [],
                "departments": [],
            }
        )

    batch_ids = [item.id for item in selected_batches]
    all_results = AttendanceResult.objects.filter(batch_id__in=batch_ids).select_related("employee")
    available_departments = sorted(
        department or "未分组"
        for department in all_results.order_by().values_list("employee__department", flat=True).distinct()
    )
    selected_department = request.query_params.get("department", "").strip()
    results = all_results
    if selected_department:
        if selected_department == "未分组":
            results = results.filter(employee__department="")
        else:
            results = results.filter(employee__department=selected_department)
    totals = results.aggregate(actual=Sum("actual_days"), due=Sum("due_days"))
    actual = totals["actual"] or Decimal("0")
    due = totals["due"] or Decimal("0")
    attendance_rate = min(float(actual / due * 100), 100) if due else 0
    employee_count = results.values("employee_id").distinct().count()
    employee_counts_by_batch = {
        row["batch_id"]: row["count"]
        for row in results.values("batch_id").annotate(count=Count("employee_id", distinct=True))
    }
    start_date = date(start_period[0], start_period[1], 1)
    end_date = date(end_period[0], end_period[1], calendar.monthrange(end_period[0], end_period[1])[1])
    raw_days = RawPunchDay.objects.filter(
            batch_id__in=batch_ids,
            work_date__range=(start_date, end_date),
            employee__isnull=False,
            effective_has_punch=True,
        )
    if selected_department:
        raw_days = raw_days.filter(
            employee__department="" if selected_department == "未分组" else selected_department
        )
    daily_rows = (
        raw_days
        .values("batch_id", "work_date")
        .annotate(count=Count("employee", distinct=True))
        .order_by("work_date")
    )
    daily = [
        {
            "date": row["work_date"].isoformat(),
            "count": row["count"],
            "rate": round(row["count"] / employee_counts_by_batch.get(row["batch_id"], 1) * 100, 1),
        }
        for row in daily_rows
    ]
    department_rows = (
        results.values("employee__department")
        .annotate(
            employees=Count("employee_id", distinct=True),
            actual=Sum("actual_days"),
            due=Sum("due_days"),
            review_count=Count(
                "employee_id",
                distinct=True,
                filter=Q(status=AttendanceResult.Status.REVIEW),
            ),
        )
        .order_by("employee__department")
    )
    departments = []
    for row in department_rows:
        department_due = row["due"] or Decimal("0")
        departments.append(
            {
                "department": row["employee__department"] or "未分组",
                "employees": row["employees"],
                "attendance_rate": round(min(float((row["actual"] or 0) / department_due * 100), 100), 1)
                if department_due
                else 0,
                "review_count": row["review_count"],
            }
        )
    latest_batch = selected_batches[-1]
    summary = {
        "total_rows": sum(item.total_rows for item in selected_batches),
        "matched_rows": sum(item.matched_rows for item in selected_batches),
        "unmatched_rows": sum(item.unmatched_rows for item in selected_batches),
        "suspicion_count": sum(item.suspicion_count for item in selected_batches),
    }
    return Response(
        {
            "batch": ImportBatchSerializer(latest_batch).data,
            "batches": ImportBatchSerializer(selected_batches, many=True).data,
            "period": period,
            "available_periods": available_periods,
            "kpis": {
                "employees": employee_count,
                "attendance_rate": round(attendance_rate, 1),
                "review_count": results.filter(status=AttendanceResult.Status.REVIEW)
                .values("employee_id")
                .distinct()
                .count(),
                "pending_cross_day": CrossDaySuspicion.objects.filter(
                    batch_id__in=batch_ids,
                    status=CrossDaySuspicion.Status.PENDING,
                )
                .filter(
                    Q(employee__department="")
                    if selected_department == "未分组"
                    else Q(employee__department=selected_department)
                    if selected_department
                    else Q()
                )
                .count(),
                "unmatched_rows": summary["unmatched_rows"],
            },
            "summary": summary,
            "selected_department": selected_department,
            "available_departments": available_departments,
            "daily": daily,
            "departments": departments,
        }
    )
