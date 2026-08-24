import secrets
from pathlib import Path
from datetime import timedelta
from dataclasses import asdict

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status

from .models import BossAccount, JobApplication, RecruitmentAuditLog, RecruitmentJob, Resume, RpaTask, RpaWorker
from .rpa.tasks import append_event
from .rpa.sync import sync_positions
from .services.discovery import sync_discoveries
from .services.communications import complete_communication_task
from .services.communications import sync_conversation_states
from .services.resumes import archive_pdf
from .services.task_recovery import recover_stale_tasks


class HasRpaWorkerToken(BasePermission):
    def has_permission(self, request, view):
        supplied = request.headers.get("X-RPA-Worker-Token", "")
        expected = settings.RPA_WORKER_TOKEN
        return bool(supplied and expected and secrets.compare_digest(supplied, expected))


def _worker(request):
    key = str(request.data.get("worker_key", ""))[:100]
    if not key:
        return None
    return RpaWorker.objects.filter(key=key).first()


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
def heartbeat_view(request):
    key = str(request.data.get("worker_key", ""))[:100]
    hostname = str(request.data.get("hostname", ""))[:255]
    if not key or not hostname:
        return Response({"detail": "worker_key 和 hostname 必填"}, status=status.HTTP_400_BAD_REQUEST)
    worker, _ = RpaWorker.objects.update_or_create(
        key=key,
        defaults={
            "hostname": hostname,
            "version": str(request.data.get("version", ""))[:80],
            "status": RpaWorker.Status.ONLINE,
            "capabilities": request.data.get("capabilities") if isinstance(request.data.get("capabilities"), dict) else {},
            "last_seen_at": timezone.now(),
        },
    )
    return Response({"worker_key": worker.key, "status": worker.status, "last_seen_at": worker.last_seen_at})


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
@transaction.atomic
def lease_task_view(request):
    worker = _worker(request)
    if worker is None:
        return Response({"detail": "Worker 尚未注册"}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    recover_stale_tasks(now=now)
    task = (
        RpaTask.objects.select_for_update()
        .select_related("boss_account")
        .filter(Q(status=RpaTask.Status.PENDING) | Q(status=RpaTask.Status.LEASED, lease_expires_at__lt=now))
        .order_by("created_at")
        .first()
    )
    if task is None:
        return Response({"task": None})
    task.status = RpaTask.Status.LEASED
    task.worker = worker
    task.lease_expires_at = now + timedelta(seconds=60)
    task.save(update_fields=["status", "worker", "lease_expires_at", "updated_at"])
    account = task.boss_account
    account.status = BossAccount.Status.RUNNING
    account.save(update_fields=["status", "updated_at"])
    append_event(task=task, event="leased", message="任务已由本机 Worker 领取", data={"worker_key": worker.key})
    return Response({"task": {
        "id": str(task.pk),
        "action": task.action,
        "open_login": bool(task.request_payload.get("open_login", False)),
        "request_payload": task.request_payload,
        "browser": {
            "type": account.browser_type,
            "executable": account.browser_executable,
            "user_data_dir": account.user_data_dir,
            "cdp_port": account.cdp_port,
        },
    }})


def _assigned_task(request, task_id):
    worker = _worker(request)
    if worker is None:
        return None, None
    task = RpaTask.objects.select_related("boss_account").filter(pk=task_id, worker=worker).first()
    return worker, task


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
def task_event_view(request, task_id):
    _, task = _assigned_task(request, task_id)
    if task is None:
        return Response({"detail": "任务不存在或不属于该 Worker"}, status=status.HTTP_404_NOT_FOUND)
    if task.status not in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}:
        return Response({"detail": "任务已结束"}, status=status.HTTP_409_CONFLICT)
    now = timezone.now()
    if task.status == RpaTask.Status.LEASED:
        task.status = RpaTask.Status.RUNNING
        task.started_at = now
    task.lease_expires_at = now + timedelta(seconds=120)
    task.save(update_fields=["status", "started_at", "lease_expires_at", "updated_at"])
    event = append_event(
        task=task,
        event=str(request.data.get("event", "progress"))[:64],
        message=str(request.data.get("message", ""))[:500],
        data=request.data.get("data") if isinstance(request.data.get("data"), dict) else {},
        level=str(request.data.get("level", "info"))[:16],
    )
    return Response({"id": event.id}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
@transaction.atomic
def complete_task_view(request, task_id):
    _, task = _assigned_task(request, task_id)
    if task is None:
        return Response({"detail": "任务不存在或不属于该 Worker"}, status=status.HTTP_404_NOT_FOUND)
    if task.status not in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}:
        return Response({"detail": "任务已结束"}, status=status.HTTP_409_CONFLICT)
    terminal = {RpaTask.Status.WAITING_HUMAN, RpaTask.Status.SUCCEEDED, RpaTask.Status.FAILED}
    completed_status = request.data.get("status")
    if completed_status not in terminal:
        return Response({"detail": "任务完成状态无效"}, status=status.HTTP_400_BAD_REQUEST)
    result = request.data.get("result") if isinstance(request.data.get("result"), dict) else {}
    if task.action == RpaTask.Action.SYNC_POSITIONS and completed_status == RpaTask.Status.SUCCEEDED:
        rows = result.get("positions")
        if not isinstance(rows, list):
            return Response({"detail": "职位同步结果无效"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = {"sync": asdict(sync_positions(account=task.boss_account, owner=task.created_by, rows=rows))}
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    discovery_sources = {
        RpaTask.Action.RECOMMEND_CANDIDATES: "recommend",
        RpaTask.Action.SEARCH_CANDIDATES: "search",
        RpaTask.Action.DEEP_MATCH: "deep_search",
    }
    if task.action in discovery_sources and completed_status == RpaTask.Status.SUCCEEDED:
        rows = result.get("candidates")
        if not isinstance(rows, list):
            return Response({"detail": "候选人发现结果无效"}, status=status.HTTP_400_BAD_REQUEST)
        job = RecruitmentJob.objects.filter(
            pk=task.request_payload.get("job"),
            boss_account=task.boss_account,
        ).first()
        if job is None:
            return Response({"detail": "候选人发现职位无效"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            synced = sync_discoveries(
                account=task.boss_account,
                job=job,
                source=discovery_sources[task.action],
                criteria=task.request_payload.get("criteria", {}),
                rows=rows,
            )
            result = {"sync": asdict(synced)}
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if task.action == RpaTask.Action.SYNC_CONVERSATIONS and completed_status == RpaTask.Status.SUCCEEDED:
        rows = result.get("conversations")
        try:
            sync_result = sync_conversation_states(account=task.boss_account, rows=rows, actor=task.created_by)
            archived = 0
            incoming = (Path(settings.MEDIA_ROOT) / "rpa-incoming").resolve()
            for row in rows:
                applications = list(JobApplication.objects.filter(
                    job__boss_account=task.boss_account,
                    candidate__name=str(row.get("name", "")).strip(),
                )[:2])
                if len(applications) != 1:
                    continue
                for attachment in row.get("attachments") if isinstance(row.get("attachments"), list) else []:
                    raw_path = Path(str(attachment.get("path", "")))
                    try:
                        resolved = raw_path.resolve(strict=True)
                        if incoming not in resolved.parents or resolved.suffix.lower() != ".pdf":
                            continue
                        _, created = archive_pdf(
                            application=applications[0],
                            filename=attachment.get("filename", "附件简历.pdf"),
                            content=resolved.read_bytes(),
                            source=Resume.Source.BOSS,
                            actor=task.created_by,
                        )
                        resolved.unlink(missing_ok=True)
                        archived += int(created)
                    except (OSError, ValueError):
                        continue
            sync_result["attachments_archived"] = archived
            result = {"sync": sync_result}
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if task.action == RpaTask.Action.VIEW_ONLINE_RESUME and completed_status == RpaTask.Status.SUCCEEDED:
        raw_path = Path(str(result.get("pdf_path", "")))
        incoming = (Path(settings.MEDIA_ROOT) / "rpa-incoming").resolve()
        try:
            resolved = raw_path.resolve(strict=True)
            if incoming not in resolved.parents or resolved.suffix.lower() != ".pdf":
                raise ValueError
            application = JobApplication.objects.get(
                pk=task.request_payload.get("application_id"),
                job__boss_account=task.boss_account,
            )
            resume, created = archive_pdf(
                application=application,
                filename=result.get("filename", "在线简历.pdf"),
                content=resolved.read_bytes(),
                source=Resume.Source.BOSS,
                actor=task.created_by,
            )
            resolved.unlink(missing_ok=True)
            result = {"resume_id": resume.pk, "created": created, "verified": True}
        except (OSError, ValueError, JobApplication.DoesNotExist):
            return Response({"detail": "在线简历结果文件无效"}, status=status.HTTP_400_BAD_REQUEST)
    communication_actions = {
        RpaTask.Action.GREET,
        RpaTask.Action.REQUEST_RESUME,
        RpaTask.Action.SEND_INTERVIEW,
    }
    if task.action in communication_actions:
        complete_communication_task(
            task=task,
            status=completed_status,
            result=result,
            error_code=request.data.get("error_code", ""),
            error_message=request.data.get("error_message", ""),
        )
        append_event(task=task, event="completed", message="沟通任务执行结束", data={"status": completed_status})
        account = task.boss_account
        if completed_status == RpaTask.Status.WAITING_HUMAN:
            account.status = BossAccount.Status.PAUSED
        else:
            account.status = BossAccount.Status.READY
        account.save(update_fields=["status", "updated_at"])
        RecruitmentAuditLog.objects.create(
            boss_account=account,
            action="communication_task_completed",
            target_id=str(task.pk),
            detail={"status": completed_status, "error_code": task.error_code},
        )
        return Response({"id": str(task.pk), "status": task.status})
    task.status = completed_status
    task.result = result
    task.error_code = str(request.data.get("error_code", ""))[:64]
    task.error_message = str(request.data.get("error_message", ""))[:2000]
    task.completed_at = timezone.now()
    task.lease_expires_at = None
    task.save(update_fields=["status", "result", "error_code", "error_message", "completed_at", "lease_expires_at", "updated_at"])
    append_event(task=task, event="completed", message="任务执行结束", data={"status": completed_status})

    account = task.boss_account
    login_status = result.get("login_status")
    if login_status in {"token_invalid", "risk_control"}:
        result_verification = login_status
        login_status = BossAccount.LoginStatus.WAITING_HUMAN
    else:
        result_verification = result.get("verification_status", "")
    if login_status in BossAccount.LoginStatus.values:
        account.login_status = login_status
        account.verification_status = str(result_verification)[:40]
        account.last_checked_at = timezone.now()
        if account.verification_status in {"token_invalid", "risk_control"}:
            account.status = BossAccount.Status.RISK
        elif login_status == BossAccount.LoginStatus.READY:
            account.status = BossAccount.Status.READY
        elif login_status in {BossAccount.LoginStatus.BROWSER_STOPPED, BossAccount.LoginStatus.WAITING_LOGIN}:
            account.status = BossAccount.Status.OFFLINE
        account.save(update_fields=["login_status", "verification_status", "last_checked_at", "status", "updated_at"])
    elif task.action in {RpaTask.Action.SYNC_POSITIONS, *discovery_sources} and completed_status == RpaTask.Status.SUCCEEDED:
        account.status = BossAccount.Status.READY
        account.save(update_fields=["status", "updated_at"])
    RecruitmentAuditLog.objects.create(
        boss_account=account,
        action="task_completed",
        target_id=str(task.pk),
        detail={"status": completed_status, "error_code": task.error_code},
    )
    return Response({"id": str(task.pk), "status": task.status})
