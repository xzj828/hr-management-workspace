import hashlib
import secrets
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import asdict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Subquery
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status

from .models import AutomationApproval, AutomationEvidence, BossAccount, CandidateDiscovery, ConversationAction, ExecutionBatch, JobApplication, MessageAttachment, RecruitmentAuditLog, RecruitmentAutomationPlan, RecruitmentJob, Resume, RpaTask, RpaWorker, SearchCampaign, StepExecution, WorkflowNodeRun, WorkflowRun
from .rpa.tasks import append_event
from .rpa.sync import sync_positions
from .services.discovery import _fingerprint, import_discoveries, sync_discoveries
from .services.communications import complete_communication_task
from .services.communications import sync_conversation_states
from .services.resumes import archive_online_resume_image, archive_pdf
from .services.conversation_ingestion import (
    ingest_conversation,
    process_pending_messages,
    recover_unfulfilled_resume_requests,
)
from .services.task_recovery import recover_stale_tasks
from .services.account_status import apply_account_observation
from .services.message_scheduling import schedule_due_conversation_syncs
from .services.screening import (
    cancel_stale_rejection_task_before_lease,
    rejection_task_snapshot_is_current,
)
from .services.sqlite_lifecycle import serialize_sqlite_lifecycle


class HasRpaWorkerToken(BasePermission):
    def has_permission(self, request, view):
        supplied = request.headers.get("X-RPA-Worker-Token", "")
        expected = settings.RPA_WORKER_TOKEN
        return bool(supplied and expected and secrets.compare_digest(supplied, expected))


def _worker(request):
    key = str(request.data.get("worker_key", "") or request.query_params.get("worker_key", ""))[:100]
    if not key:
        return None
    return RpaWorker.objects.filter(key=key).first()


def _raw_passive_scopes(task):
    if task.action != RpaTask.Action.SYNC_CONVERSATIONS:
        return None
    payload = task.request_payload if isinstance(task.request_payload, dict) else {}
    scopes = payload.get("passive_plan_scopes")
    if isinstance(scopes, dict):
        return scopes
    if task.automation_plan_revision_id and payload.get("job"):
        return {
            str(payload["job"]): {
                "revision_id": task.automation_plan_revision_id,
                "generation": task.automation_generation,
            }
        }
    return None


def _valid_passive_scope_plans(task):
    scopes = _raw_passive_scopes(task)
    if scopes is None:
        return None
    from .services.automation_plans import current_passive_plan_for_sync

    valid = {}
    for raw_job_id in scopes:
        if not str(raw_job_id).isdigit():
            continue
        plan = current_passive_plan_for_sync(job_id=int(raw_job_id), scopes=scopes)
        if plan is not None:
            valid[plan.job_id] = plan
    # A shared browser read cannot reliably tell which job an account-level
    # conversation belongs to before opening it.  If any frozen scope changed,
    # stop and discard the whole poll; a later poll is scheduled with the
    # remaining jobs' fresh scope instead of continuing to read stopped jobs.
    return valid if len(valid) == len(scopes) else {}


def _scope_job_ids(scopes):
    return sorted({int(value) for value in (scopes or {}) if str(value).isdigit()})


def _safe_incoming_path(raw_value, *, suffix):
    incoming = (Path(settings.MEDIA_ROOT) / "rpa-incoming").resolve()
    try:
        resolved = Path(str(raw_value or "")).resolve(strict=True)
    except (OSError, ValueError):
        return None
    if incoming not in resolved.parents or resolved.suffix.lower() != suffix:
        return None
    return resolved


def _set_account_runtime_status(account, desired_status):
    account.status = (
        BossAccount.Status.OFFLINE
        if not account.active or account.archived_at is not None
        else desired_status
    )
    account.save(update_fields=["status", "updated_at"])


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


@api_view(["GET"])
@permission_classes([HasRpaWorkerToken])
def status_targets_view(request):
    accounts = BossAccount.objects.filter(active=True).order_by("id")
    return Response({"accounts": [
        {
            "id": account.pk,
            "browser": {
                "type": account.browser_type,
                "executable": account.browser_executable,
                "user_data_dir": account.user_data_dir,
                "cdp_port": account.cdp_port,
            },
        }
        for account in accounts
    ]})


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
def status_observations_view(request):
    observations = request.data.get("observations")
    if not isinstance(observations, list) or len(observations) > 200:
        return Response({"detail": "observations 必须是最多 200 项的数组"}, status=status.HTTP_400_BAD_REQUEST)
    accounts = {
        account.pk: account
        for account in BossAccount.objects.filter(pk__in=[item.get("account_id") for item in observations if isinstance(item, dict)])
    }
    updated = 0
    for item in observations:
        if not isinstance(item, dict) or item.get("account_id") not in accounts:
            continue
        try:
            apply_account_observation(
                account=accounts[item["account_id"]],
                login_status=str(item.get("login_status", "")),
                verification_status=item.get("verification_status", ""),
                detail=item.get("detail", ""),
            )
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        updated += 1
    return Response({"updated": updated})


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
@serialize_sqlite_lifecycle
@transaction.atomic
def lease_task_view(request):
    worker = _worker(request)
    if worker is None:
        return Response({"detail": "Worker 尚未注册"}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    recover_stale_tasks(now=now)
    schedule_due_conversation_syncs(now=now)
    busy_account_ids = RpaTask.objects.filter(
        status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING]
    ).values("boss_account_id")
    candidate_tasks = (
        RpaTask.objects.select_related("boss_account")
        .filter(status=RpaTask.Status.PENDING)
        .exclude(boss_account_id__in=Subquery(busy_account_ids))
        .filter(
            Q(workflow_node_run__isnull=True)
            | Q(
                workflow_node_run__status__in=[
                    WorkflowNodeRun.Status.BLOCKED,
                    WorkflowNodeRun.Status.READY,
                    WorkflowNodeRun.Status.RUNNING,
                    WorkflowNodeRun.Status.WAITING_HUMAN,
                ],
                workflow_node_run__run__status__in=[
                    WorkflowRun.Status.RUNNING,
                    WorkflowRun.Status.WAITING_HUMAN,
                ],
            )
        )
        .order_by("created_at")
    )
    task = None
    for _ in range(100):
        candidate_task = candidate_tasks.first()
        if candidate_task is None:
            break
        passive_scopes = _raw_passive_scopes(candidate_task)
        if (
            candidate_task.action == RpaTask.Action.SYNC_CONVERSATIONS
            and passive_scopes is not None
            and not candidate_task.automation_plan_revision_id
        ):
            BossAccount.objects.select_for_update().get(pk=candidate_task.boss_account_id)
            list(
                RecruitmentAutomationPlan.objects.select_for_update()
                .filter(job_id__in=_scope_job_ids(passive_scopes))
                .order_by("job_id")
            )
            scoped = RpaTask.objects.select_for_update().filter(
                pk=candidate_task.pk,
                status=RpaTask.Status.PENDING,
            ).first()
            if scoped is None:
                continue
            if not _valid_passive_scope_plans(scoped):
                scoped.status = RpaTask.Status.CANCELLED
                scoped.error_code = "automation_plan_scopes_stale"
                scoped.error_message = "该消息同步任务的部分或全部岗位订阅已停止或被新修订替代"
                scoped.completed_at = now
                scoped.save(update_fields=[
                    "status", "error_code", "error_message", "completed_at", "updated_at",
                ])
                append_event(task=scoped, event="cancelled", message="消息同步任务在租约前发现岗位订阅范围已变化")
                continue
            task = scoped
            break
        if candidate_task.automation_plan_revision_id:
            from .services.automation_plans import plan_fence_is_current

            account = BossAccount.objects.select_for_update().get(pk=candidate_task.boss_account_id)
            RecruitmentAutomationPlan.objects.select_for_update().get(
                revisions__pk=candidate_task.automation_plan_revision_id,
            )
            if not plan_fence_is_current(
                revision_id=candidate_task.automation_plan_revision_id,
                generation=candidate_task.automation_generation,
            ):
                stale = RpaTask.objects.select_for_update().filter(
                    pk=candidate_task.pk,
                    status=RpaTask.Status.PENDING,
                ).first()
                if stale is not None:
                    stale.status = RpaTask.Status.CANCELLED
                    stale.error_code = "automation_plan_generation_stale"
                    stale.error_message = "招聘自动化方案已暂停、停止或被新修订替代"
                    stale.completed_at = now
                    stale.save(update_fields=[
                        "status", "error_code", "error_message", "completed_at", "updated_at",
                    ])
                    append_event(task=stale, event="cancelled", message="任务在租约前被方案控制栅栏取消")
                continue
            task = (
                RpaTask.objects.select_for_update()
                .select_related("boss_account")
                .filter(pk=candidate_task.pk, status=RpaTask.Status.PENDING)
                .first()
            )
            if task is not None:
                break
            continue
        if candidate_task.action != RpaTask.Action.REJECTION_NOTICE:
            task = (
                RpaTask.objects.select_for_update()
                .select_related("boss_account")
                .filter(pk=candidate_task.pk, status=RpaTask.Status.PENDING)
                .first()
            )
            if task is not None:
                break
            continue

        # Rejection guards always lock account -> application -> task/action/step.
        # Decision and stage services use the same order, preventing stale sends and deadlocks.
        account = BossAccount.objects.select_for_update().get(pk=candidate_task.boss_account_id)
        payload = candidate_task.request_payload if isinstance(candidate_task.request_payload, dict) else {}
        target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        application_id = target.get("application_id")
        if not application_id:
            application_id = ConversationAction.objects.filter(
                pk=payload.get("conversation_action_id")
            ).values_list("application_id", flat=True).first()
        application = (
            JobApplication.objects.select_for_update()
            .select_related("job", "candidate")
            .filter(pk=application_id, job__boss_account=account)
            .first()
        )
        task = (
            RpaTask.objects.select_for_update()
            .select_related("boss_account", "approval")
            .filter(pk=candidate_task.pk, status=RpaTask.Status.PENDING)
            .first()
        )
        if task is None:
            continue
        if application is None:
            action = (
                ConversationAction.objects.select_for_update()
                .filter(pk=payload.get("conversation_action_id"))
                .first()
            )
            cancel_stale_rejection_task_before_lease(
                task=task,
                application=None,
                action=action,
            )
            append_event(
                task=task,
                event="cancelled",
                message="租约前复核发现未通过通知目标无效，任务已取消",
            )
            task = None
            continue
        valid, conversation_action = rejection_task_snapshot_is_current(
            task=task,
            application=application,
        )
        if not valid:
            cancel_stale_rejection_task_before_lease(
                task=task,
                application=application,
                action=conversation_action,
            )
            task = None
            continue
        break
    if task is None:
        return Response({"task": None})
    task.status = RpaTask.Status.LEASED
    task.worker = worker
    task.lease_expires_at = now + timedelta(seconds=60)
    task.lease_generation += 1
    task.lease_token = uuid.uuid4()
    task.save(update_fields=[
        "status", "worker", "lease_expires_at", "lease_generation", "lease_token", "updated_at",
    ])
    account = task.boss_account
    account.status = BossAccount.Status.RUNNING
    account.save(update_fields=["status", "updated_at"])
    append_event(task=task, event="leased", message="任务已由本机 Worker 领取", data={"worker_key": worker.key})
    return Response({"task": {
        "id": str(task.pk),
        "action": task.action,
        "lease_token": str(task.lease_token),
        "lease_generation": task.lease_generation,
        "open_login": bool(task.request_payload.get("open_login", False)),
        "request_payload": task.request_payload,
        "browser": {
            "type": account.browser_type,
            "executable": account.browser_executable,
            "user_data_dir": account.user_data_dir,
            "cdp_port": account.cdp_port,
        },
    }})


def _lock_task_for_worker(request, task_id):
    """Lock account/domain before task and bind the call to one exact lease."""
    worker = _worker(request)
    if worker is None:
        return None, None, "worker_missing"
    snapshot = RpaTask.objects.filter(pk=task_id).values(
        "action", "boss_account_id", "request_payload", "automation_plan_revision_id"
    ).first()
    if snapshot is None:
        return worker, None, "task_missing"
    if snapshot["automation_plan_revision_id"]:
        BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
        RecruitmentAutomationPlan.objects.select_for_update().get(
            revisions__pk=snapshot["automation_plan_revision_id"],
        )
        task = (
            RpaTask.objects.select_for_update()
            .select_related("boss_account")
            .filter(pk=task_id)
            .first()
        )
    elif (
        snapshot["action"] == RpaTask.Action.SYNC_CONVERSATIONS
        and isinstance((snapshot["request_payload"] or {}).get("passive_plan_scopes"), dict)
    ):
        scopes = snapshot["request_payload"]["passive_plan_scopes"]
        BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
        list(
            RecruitmentAutomationPlan.objects.select_for_update()
            .filter(job_id__in=_scope_job_ids(scopes))
            .order_by("job_id")
        )
        task = (
            RpaTask.objects.select_for_update()
            .select_related("boss_account")
            .filter(pk=task_id)
            .first()
        )
    elif snapshot["action"] == RpaTask.Action.REJECTION_NOTICE:
        BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
        payload = snapshot["request_payload"] if isinstance(snapshot["request_payload"], dict) else {}
        target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        application_id = target.get("application_id")
        if application_id:
            JobApplication.objects.select_for_update().filter(
                pk=application_id,
                job__boss_account_id=snapshot["boss_account_id"],
            ).first()
        task = (
            RpaTask.objects.select_for_update()
            .select_related("boss_account")
            .filter(pk=task_id)
            .first()
        )
    else:
        task = (
            RpaTask.objects.select_for_update()
            .select_related("boss_account")
            .filter(pk=task_id)
            .first()
        )
    if task is None:
        return worker, None, "task_missing"
    if task.worker_id != worker.pk:
        return worker, task, "worker_changed"
    supplied_token = str(
        request.data.get("lease_token")
        or request.query_params.get("lease_token", "")
    ).strip()
    try:
        supplied_generation = int(
            request.data.get("lease_generation")
            or request.query_params.get("lease_generation")
        )
    except (TypeError, ValueError):
        supplied_generation = -1
    if (
        task.lease_token is None
        or supplied_token != str(task.lease_token)
        or supplied_generation != task.lease_generation
    ):
        return worker, task, "lease_changed"
    return worker, task, "assigned"


class SearchPullResultError(ValueError):
    def __init__(self, message, *, evidence_context=None):
        super().__init__(message)
        self.evidence_context = evidence_context


def _schedule_workflow_resume(task):
    if not task.workflow_node_run_id:
        return
    if task.automation_plan_revision_id:
        from .services.automation_plans import plan_fence_is_current

        if not plan_fence_is_current(
            revision_id=task.automation_plan_revision_id,
            generation=task.automation_generation,
        ):
            return
    task_id = task.pk

    def resume_workflow():
        from .services.workflow_nodes import resume_workflow_for_task
        current = RpaTask.objects.get(pk=task_id)
        if current.automation_plan_revision_id:
            from .services.automation_plans import plan_fence_is_current

            if not plan_fence_is_current(
                revision_id=current.automation_plan_revision_id,
                generation=current.automation_generation,
            ):
                return
        resume_workflow_for_task(current)

    transaction.on_commit(resume_workflow)


def _validate_search_pull_result(*, task, campaign, result):
    """Validate the immutable approval scope and all worker output before writes."""
    approval = task.approval
    approved_payload = approval.payload if approval and isinstance(approval.payload, dict) else {}
    if (
        approval is None
        or approval.action != AutomationApproval.Action.SEARCH_AND_PULL_RESUMES
        or approval.status != AutomationApproval.Status.APPROVED
        or approved_payload != task.request_payload
        or approved_payload.get("campaign_id") != campaign.pk
    ):
        raise SearchPullResultError("主动寻访任务缺少有效的已确认快照")
    expected_task_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
    conflicting_task = RpaTask.objects.filter(
        action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
        boss_account=task.boss_account,
        request_payload__campaign_id=campaign.pk,
        status__in=[
            RpaTask.Status.PENDING,
            RpaTask.Status.LEASED,
            RpaTask.Status.RUNNING,
            RpaTask.Status.WAITING_HUMAN,
            RpaTask.Status.SUCCEEDED,
        ],
    ).exclude(pk=task.pk).exists()
    if (
        task.idempotency_key != expected_task_key
        or campaign.status not in {SearchCampaign.Status.QUEUED, SearchCampaign.Status.RUNNING}
        or approval.rpa_tasks.exclude(pk=task.pk).exists()
        or conflicting_task
    ):
        raise SearchPullResultError("主动寻访 task、approval 与 campaign 的唯一关联无效")

    try:
        max_scan_count = int(approved_payload.get("max_scan_count", 0) or 0)
        target_resume_count = int(approved_payload.get("target_resume_count", 0) or 0)
        resume_view_budget = int(approved_payload.get("resume_view_budget", 0) or 0)
        scanned_count = int(result.get("scanned_count", -1))
        view_attempt_count = int(result.get("view_attempt_count", -1))
        reported_budget = int(result.get("resume_view_budget", -1))
    except (TypeError, ValueError) as exc:
        raise SearchPullResultError("主动寻访结果中的数量字段无效") from exc

    rows = result.get("candidates")
    pulled_rows = result.get("resumes")
    raw_attempts = result.get("attempts")
    if not isinstance(rows, list) or not isinstance(pulled_rows, list) or not isinstance(raw_attempts, list):
        raise SearchPullResultError("主动寻访结果缺少候选人、简历或逐次查看证据")
    if (
        max_scan_count < 1
        or target_resume_count < 1
        or resume_view_budget != approval.item_count
        or resume_view_budget != reported_budget
        or len(rows) > max_scan_count
        or scanned_count != len(rows)
        or view_attempt_count < 0
        or view_attempt_count > resume_view_budget
        or len(pulled_rows) > target_resume_count
        or len(raw_attempts) > max_scan_count
    ):
        raise SearchPullResultError("主动寻访结果超出已确认的搜索或简历查看范围")

    candidate_identities = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SearchPullResultError("候选人发现结果无效")
        name = str(row.get("display_name", "")).strip()
        external_id = str(row.get("external_id", "")).strip()
        if not name:
            raise SearchPullResultError("候选人缺少展示名称")
        fingerprint = _fingerprint(task.boss_account_id, row)
        existing_identity = candidate_identities.get(fingerprint)
        identity = {"name": name, "external_id": external_id}
        if existing_identity is not None and existing_identity != identity:
            raise SearchPullResultError("候选人身份指纹冲突")
        candidate_identities[fingerprint] = identity

    attempts = []
    attempt_fingerprints = set()
    successful_fingerprints = set()
    actual_attempts = 0
    controlled_attempt_errors = {
        "identity_ambiguous": "identity_ambiguous",
        "target_identity_unverifiable": "target_identity_unverifiable",
        "stable_action_unavailable": "stable_action_unavailable",
        "preview_failed": "preview_failed",
        "preview_succeeded": "",
    }
    for expected_sequence, raw_attempt in enumerate(raw_attempts, start=1):
        if not isinstance(raw_attempt, dict):
            raise SearchPullResultError("在线简历查看证据无效")
        name = str(raw_attempt.get("name", "")).strip()
        fingerprint = str(raw_attempt.get("fingerprint", "")).strip()
        verified = raw_attempt.get("verified")
        preview_attempted = raw_attempt.get("preview_attempted")
        outcome = str(raw_attempt.get("outcome", "")).strip()
        error_code = str(raw_attempt.get("error_code", "")).strip()
        sequence = raw_attempt.get("sequence")
        timestamp = str(raw_attempt.get("timestamp", "")).strip()
        expected_external_id = str(raw_attempt.get("expected_external_id", "")).strip()
        observed_external_id = str(raw_attempt.get("observed_external_id", "")).strip()
        error = raw_attempt.get("error", "")
        if not isinstance(error, str):
            raise SearchPullResultError("在线简历查看错误证据无效")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise SearchPullResultError("在线简历查看证据时间无效") from exc
        if (
            not name
            or fingerprint not in candidate_identities
            or candidate_identities[fingerprint]["name"] != name
            or candidate_identities[fingerprint]["external_id"] != expected_external_id
            or fingerprint in attempt_fingerprints
            or not isinstance(verified, bool)
            or not isinstance(preview_attempted, bool)
            or sequence != expected_sequence
            or parsed_timestamp.tzinfo is None
            or outcome not in controlled_attempt_errors
            or error_code != controlled_attempt_errors[outcome]
        ):
            raise SearchPullResultError("在线简历查看身份或去重证据无效")
        if preview_attempted:
            if (
                verified is not True
                or outcome not in {"preview_succeeded", "preview_failed"}
                or not expected_external_id
                or observed_external_id != expected_external_id
            ):
                raise SearchPullResultError("在线简历实际查看结果无效")
            actual_attempts += 1
        else:
            valid_blocked_outcomes = {
                "identity_ambiguous": False,
                "target_identity_unverifiable": False,
                "stable_action_unavailable": True,
            }
            if outcome not in valid_blocked_outcomes or verified is not valid_blocked_outcomes[outcome]:
                raise SearchPullResultError("未执行查看的身份核验结果无效")
            if outcome == "stable_action_unavailable" and (
                not expected_external_id or observed_external_id != expected_external_id
            ):
                raise SearchPullResultError("转人工查看的稳定身份复核结果无效")
            if outcome == "target_identity_unverifiable" and (
                expected_external_id or observed_external_id
            ):
                raise SearchPullResultError("缺少稳定身份的查看证据无效")
            if outcome == "identity_ambiguous" and observed_external_id:
                raise SearchPullResultError("身份不唯一时不得声明已观察到稳定身份")
        attempt_fingerprints.add(fingerprint)
        if outcome == "preview_succeeded":
            successful_fingerprints.add(fingerprint)
        attempts.append({
            "name": name,
            "fingerprint": fingerprint,
            "verified": verified,
            "preview_attempted": preview_attempted,
            "outcome": outcome,
            "error_code": error_code,
            "sequence": sequence,
            "timestamp": timestamp,
            "expected_external_id": expected_external_id,
            "observed_external_id": observed_external_id,
            "error": error[:1000],
        })

    evidence_context = {
        "campaign_id": campaign.pk,
        "attempts": attempts,
        "reserved_resume_views": resume_view_budget,
        "actual_preview_attempts": actual_attempts,
        "unused_resume_views": resume_view_budget - actual_attempts,
        "scanned_count": scanned_count,
        "actual_known": True,
        "evidence_untrusted": False,
    }
    if actual_attempts != view_attempt_count:
        raise SearchPullResultError(
            "在线简历实际查看次数与逐次证据不一致",
            evidence_context=evidence_context,
        )

    prepared_resumes = []
    pulled_fingerprints = set()
    resolved_paths = set()
    incoming = (Path(settings.MEDIA_ROOT) / "rpa-incoming").resolve()
    for item in pulled_rows:
        candidate_row = item.get("candidate") if isinstance(item, dict) else None
        identity = item.get("identity_snapshot") if isinstance(item, dict) else None
        if not isinstance(candidate_row, dict) or not isinstance(identity, dict):
            raise SearchPullResultError(
                "在线简历缺少执行前身份复核证据",
                evidence_context=evidence_context,
            )
        fingerprint = _fingerprint(task.boss_account_id, candidate_row)
        name = str(candidate_row.get("display_name", "")).strip()
        external_id = str(candidate_row.get("external_id", "")).strip()
        if (
            identity.get("verified") is not True
            or not name
            or not external_id
            or str(identity.get("name", "")).strip() != name
            or str(identity.get("external_id", "")).strip() != external_id
            or str(identity.get("expected_external_id", "")).strip() != external_id
            or str(identity.get("observed_external_id", "")).strip() != external_id
            or str(identity.get("fingerprint", "")) != fingerprint
            or fingerprint in pulled_fingerprints
            or fingerprint not in successful_fingerprints
        ):
            raise SearchPullResultError(
                "在线简历身份复核证据无效或重复",
                evidence_context=evidence_context,
            )
        raw_path = Path(str(item.get("path", "")))
        try:
            resolved = raw_path.resolve(strict=True)
            content = resolved.read_bytes()
        except OSError as exc:
            raise SearchPullResultError(
                "在线简历结果文件不可读",
                evidence_context=evidence_context,
            ) from exc
        if (
            incoming not in resolved.parents
            or resolved.suffix.lower() != ".png"
            or resolved in resolved_paths
            or not content.startswith(b"\x89PNG\r\n\x1a\n")
            or len(content) > 25 * 1024 * 1024
        ):
            raise SearchPullResultError(
                "在线简历路径或文件内容无效",
                evidence_context=evidence_context,
            )
        pulled_fingerprints.add(fingerprint)
        resolved_paths.add(resolved)
        prepared_resumes.append({
            "candidate": candidate_row,
            "fingerprint": fingerprint,
            "path": resolved,
            "content": content,
            "filename": item.get("filename", f"{name}-在线简历.png"),
        })

    if pulled_fingerprints != successful_fingerprints:
        raise SearchPullResultError(
            "在线简历成功查看证据与归档结果不一致",
            evidence_context=evidence_context,
        )
    return {
        **evidence_context,
        "rows": rows,
        "prepared_resumes": prepared_resumes,
    }


def _controlled_search_pull_failure_code(failure_code):
    allowed_failure_codes = {
        "",
        "search_pull_persist_failed",
        "search_pull_result_invalid",
        "search_campaign_missing",
        "cancelled_by_user",
        "stable_identity_action_unavailable",
        "target_identity_unverifiable",
        "worker_reported_failure",
    }
    value = str(failure_code)
    return value if value in allowed_failure_codes else "worker_reported_failure"


def _unknown_search_pull_evidence_context(*, task, campaign=None):
    approval = task.approval
    payload = task.request_payload if isinstance(task.request_payload, dict) else {}
    if (
        approval is not None
        and approval.action == AutomationApproval.Action.SEARCH_AND_PULL_RESUMES
        and approval.boss_account_id == task.boss_account_id
    ):
        reserved = approval.item_count
    else:
        try:
            reserved = int(payload.get("resume_view_budget", 0) or 0)
        except (TypeError, ValueError):
            reserved = 0
    reserved = max(0, reserved)
    return {
        "campaign_id": campaign.pk if campaign is not None else payload.get("campaign_id"),
        "attempts": [],
        "reserved_resume_views": reserved,
        "actual_preview_attempts": None,
        "unused_resume_views": None,
        "scanned_count": None,
        "actual_known": False,
        "evidence_untrusted": True,
    }


def _persist_search_pull_evidence(*, task, context, final_status, failure_code=""):
    controlled_failure_code = _controlled_search_pull_failure_code(failure_code)
    actual_known = context.get("actual_known") is True
    evidence_untrusted = context.get("evidence_untrusted") is True
    common = {
        "campaign_id": context["campaign_id"],
        "final_status": final_status,
        "failure_code": controlled_failure_code,
        "actual_known": actual_known,
        "actual_unknown": not actual_known,
        "evidence_untrusted": evidence_untrusted,
    }
    safe_attempts = [
        {
            "sequence": attempt["sequence"],
            "timestamp": attempt["timestamp"],
            "external_id_hash": (
                hashlib.sha256(
                    f"{task.boss_account_id}:{attempt['expected_external_id']}".encode("utf-8")
                ).hexdigest()
                if attempt["expected_external_id"]
                else None
            ),
            "verified": attempt["verified"],
            "preview_attempted": attempt["preview_attempted"],
            "outcome": attempt["outcome"],
            "error_code": attempt["error_code"],
        }
        for attempt in context.get("attempts", [])
    ]
    AutomationEvidence.objects.update_or_create(
        task=task,
        kind="resume_preview_attempts",
        defaults={
            "summary": f"记录 {len(context.get('attempts', []))} 条候选人身份核验与在线简历查看尝试",
            "metadata": {
                **common,
                "attempts": safe_attempts,
                "scanned_count": context.get("scanned_count"),
                "actual_preview_attempts": context.get("actual_preview_attempts") if actual_known else None,
            },
        },
    )
    AutomationEvidence.objects.update_or_create(
        task=task,
        kind="resume_view_usage",
        defaults={
            "summary": "主动寻访在线简历查看额度对账",
            "metadata": {
                **common,
                "metric": "resume_view",
                "search_reserved": 1,
                "reserved": context["reserved_resume_views"],
                "actual": context.get("actual_preview_attempts") if actual_known else None,
                "unused": context.get("unused_resume_views") if actual_known else None,
                "unused_disposition": "retained_no_refund",
            },
        },
    )


def _complete_search_pull_success(*, task, campaign, context, user_stopped=False):
    created_files = []
    incoming_paths = []
    try:
        with transaction.atomic():
            sync_discoveries(
                account=task.boss_account,
                job=campaign.job,
                source=campaign.source,
                criteria=campaign.criteria,
                rows=context["rows"],
            )
            archived = 0
            application_ids = []
            for item in context["prepared_resumes"]:
                discovery = CandidateDiscovery.objects.get(
                    boss_account=task.boss_account,
                    job=campaign.job,
                    fingerprint=item["fingerprint"],
                )
                import_discoveries(discoveries=[discovery], actor=task.created_by)
                discovery.refresh_from_db(fields=["imported_candidate", "imported_at"])
                application = JobApplication.objects.get(
                    candidate=discovery.imported_candidate,
                    job=campaign.job,
                )
                application_ids.append(application.pk)
                resume, created = archive_online_resume_image(
                    application=application,
                    filename=item["filename"],
                    content=item["content"],
                    external_id=discovery.external_id,
                    actor=task.created_by,
                )
                if created and resume.file.name:
                    created_files.append((resume.file.storage, resume.file.name))
                archived += int(created)
                incoming_paths.append(item["path"])

            campaign.scanned_count = context["scanned_count"]
            campaign.pulled_resume_count = archived
            campaign.status = (
                SearchCampaign.Status.CANCELLED
                if user_stopped
                else SearchCampaign.Status.SUCCEEDED
            )
            campaign.stop_reason = (
                SearchCampaign.StopReason.USER_STOPPED
                if user_stopped
                else (
                    SearchCampaign.StopReason.TARGET_REACHED
                    if archived >= campaign.target_resume_count
                    else SearchCampaign.StopReason.SCAN_LIMIT
                )
            )
            campaign.error_message = ""
            campaign.completed_at = timezone.now()
            campaign.save(update_fields=[
                "scanned_count", "pulled_resume_count", "status", "stop_reason",
                "error_message", "completed_at", "updated_at",
            ])
            normalized_result = {
                "campaign_id": campaign.pk,
                "scanned_count": campaign.scanned_count,
                "pulled_resume_count": archived,
                "stop_reason": campaign.stop_reason,
                "application_ids": application_ids,
                "resume_view_usage": {
                    "reserved": context["reserved_resume_views"],
                    "actual": context["actual_preview_attempts"],
                    "unused": context["unused_resume_views"],
                    "unused_disposition": "retained_no_refund",
                },
            }
            _persist_search_pull_evidence(
                task=task,
                context=context,
                final_status=(RpaTask.Status.CANCELLED if user_stopped else RpaTask.Status.SUCCEEDED),
            )
            task.status = RpaTask.Status.CANCELLED if user_stopped else RpaTask.Status.SUCCEEDED
            task.result = normalized_result
            task.error_code = "automation_plan_stopped" if user_stopped else ""
            task.error_message = "招聘自动化方案已停止；已完成的原子结果已保留" if user_stopped else ""
            task.completed_at = timezone.now()
            task.lease_expires_at = None
            task.lease_token = None
            task.save(update_fields=[
                "status", "result", "error_code", "error_message", "completed_at",
                "lease_expires_at", "lease_token", "updated_at",
            ])
            append_event(
                task=task,
                event="cancelled" if user_stopped else "completed",
                message=(
                    "主动寻访在安全检查点停止，已保留完成的原子结果"
                    if user_stopped
                    else "主动寻访任务执行结束"
                ),
                data={"status": task.status},
            )
            account = task.boss_account
            _set_account_runtime_status(account, BossAccount.Status.READY)
            RecruitmentAuditLog.objects.create(
                boss_account=account,
                action="task_completed",
                target_id=str(task.pk),
                detail={"status": task.status, "error_code": ""},
            )
            if not user_stopped:
                _schedule_workflow_resume(task)
            for path in incoming_paths:
                transaction.on_commit(lambda resolved=path: resolved.unlink(missing_ok=True))
            return normalized_result
    except Exception:
        # Database rollback cannot remove FileField objects already written to storage.
        for storage, name in created_files:
            try:
                storage.delete(name)
            except OSError:
                pass
        raise


def _fail_search_pull_completion(
    *, task, campaign, error_message, context=None, failure_code="search_pull_persist_failed"
):
    controlled_failure_code = _controlled_search_pull_failure_code(failure_code)
    context = context or _unknown_search_pull_evidence_context(task=task, campaign=campaign)
    message = str(error_message or "主动寻访回写失败")[:2000]
    campaign.status = SearchCampaign.Status.FAILED
    campaign.stop_reason = SearchCampaign.StopReason.ERROR
    campaign.error_message = message
    campaign.pulled_resume_count = 0
    if context.get("scanned_count") is not None:
        campaign.scanned_count = context["scanned_count"]
    campaign.completed_at = timezone.now()
    campaign.save(update_fields=[
        "status", "stop_reason", "error_message", "scanned_count",
        "pulled_resume_count", "completed_at", "updated_at",
    ])
    _persist_search_pull_evidence(
        task=task,
        context=context,
        final_status=RpaTask.Status.FAILED,
        failure_code=controlled_failure_code,
    )
    task.status = RpaTask.Status.FAILED
    task.result = {
        "campaign_id": campaign.pk,
        "persistence_status": "rolled_back",
        "resume_view_usage": {
            "reserved": context["reserved_resume_views"],
            "actual_known": context.get("actual_known") is True,
            "actual": context.get("actual_preview_attempts") if context.get("actual_known") is True else None,
            "unused": context.get("unused_resume_views") if context.get("actual_known") is True else None,
            "unused_disposition": "retained_no_refund",
        },
    }
    task.error_code = controlled_failure_code
    task.error_message = message
    task.completed_at = timezone.now()
    task.lease_expires_at = None
    task.save(update_fields=[
        "status", "result", "error_code", "error_message", "completed_at",
        "lease_expires_at", "updated_at",
    ])
    append_event(
        task=task,
        event="failed",
        message="主动寻访结果未写入，业务变更已回滚",
        data={"status": task.status, "error_code": task.error_code},
        level="error",
    )
    account = task.boss_account
    _set_account_runtime_status(account, BossAccount.Status.READY)
    _schedule_workflow_resume(task)


def _fail_orphaned_search_pull_task(*, task):
    context = _unknown_search_pull_evidence_context(task=task)
    _persist_search_pull_evidence(
        task=task,
        context=context,
        final_status=RpaTask.Status.FAILED,
        failure_code="search_campaign_missing",
    )
    task.status = RpaTask.Status.FAILED
    task.result = {
        "campaign_id": task.request_payload.get("campaign_id"),
        "persistence_status": "rolled_back",
        "resume_view_usage": {
            "reserved": context["reserved_resume_views"],
            "actual_known": False,
            "actual": None,
            "unused": None,
            "unused_disposition": "retained_no_refund",
        },
    }
    task.error_code = "search_campaign_missing"
    task.error_message = "主动寻访任务引用的 campaign 不存在或不属于当前账号"
    task.completed_at = timezone.now()
    task.lease_expires_at = None
    task.save(update_fields=[
        "status", "result", "error_code", "error_message", "completed_at",
        "lease_expires_at", "updated_at",
    ])
    append_event(
        task=task,
        event="failed",
        message="主动寻访任务引用无效，已终止回写",
        data={"status": task.status, "error_code": task.error_code},
        level="error",
    )
    account = task.boss_account
    _set_account_runtime_status(account, BossAccount.Status.READY)
    _schedule_workflow_resume(task)


def _complete_search_pull_waiting_human(*, task, campaign, context, error_code, error_message):
    if context["prepared_resumes"]:
        raise SearchPullResultError(
            "等待人工处理的主动寻访结果不得包含未归档的在线简历",
            evidence_context=context,
        )
    with transaction.atomic():
        sync_discoveries(
            account=task.boss_account,
            job=campaign.job,
            source=campaign.source,
            criteria=campaign.criteria,
            rows=context["rows"],
        )
        campaign.scanned_count = context["scanned_count"]
        campaign.pulled_resume_count = 0
        campaign.status = SearchCampaign.Status.PAUSED
        campaign.stop_reason = SearchCampaign.StopReason.NONE
        campaign.error_message = str(error_message)[:2000]
        campaign.completed_at = None
        campaign.save(update_fields=[
            "scanned_count", "pulled_resume_count", "status", "stop_reason",
            "error_message", "completed_at", "updated_at",
        ])
        usage = {
            "reserved": context["reserved_resume_views"],
            "actual": context["actual_preview_attempts"],
            "unused": context["unused_resume_views"],
            "unused_disposition": "retained_no_refund",
        }
        _persist_search_pull_evidence(
            task=task,
            context=context,
            final_status=RpaTask.Status.WAITING_HUMAN,
            failure_code=error_code,
        )
        task.status = RpaTask.Status.WAITING_HUMAN
        task.result = {
            "campaign_id": campaign.pk,
            "scanned_count": context["scanned_count"],
            "pulled_resume_count": 0,
            "resume_view_usage": usage,
        }
        task.error_code = str(error_code or "stable_identity_action_unavailable")[:64]
        task.error_message = str(error_message)[:2000]
        task.completed_at = timezone.now()
        task.lease_expires_at = None
        task.save(update_fields=[
            "status", "result", "error_code", "error_message", "completed_at",
            "lease_expires_at", "updated_at",
        ])
        append_event(
            task=task,
            event="waiting_human",
            message="主动寻访已保留搜索结果，在线简历查看转人工",
            data={"status": task.status, "error_code": task.error_code},
        )
        account = task.boss_account
        _set_account_runtime_status(account, BossAccount.Status.PAUSED)
        _schedule_workflow_resume(task)


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
@serialize_sqlite_lifecycle
@transaction.atomic
def task_event_view(request, task_id):
    _, task, assignment = _lock_task_for_worker(request, task_id)
    if task is None:
        return Response({"detail": "任务不存在或不属于该 Worker"}, status=status.HTTP_404_NOT_FOUND)
    if assignment != "assigned":
        return Response({"detail": "任务租约已转移，旧 Worker 不得继续执行"}, status=status.HTTP_409_CONFLICT)
    now = timezone.now()
    if task.status not in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}:
        return Response({"detail": "任务已结束"}, status=status.HTTP_409_CONFLICT)
    if task.lease_expires_at is None or task.lease_expires_at <= now:
        return Response({"detail": "任务租约已过期，Worker 不得继续执行"}, status=status.HTTP_409_CONFLICT)
    if task.automation_plan_revision_id:
        from .services.automation_plans import plan_fence_is_current

        if not plan_fence_is_current(
            revision_id=task.automation_plan_revision_id,
            generation=task.automation_generation,
        ):
            return Response(
                {"detail": "招聘自动化方案已暂停、停止或被新修订替代"},
                status=status.HTTP_409_CONFLICT,
            )
    valid_scope_plans = _valid_passive_scope_plans(task)
    if valid_scope_plans is not None and not valid_scope_plans:
        return Response(
            {"detail": "消息同步任务的岗位订阅范围已变化，必须使用新范围重新同步"},
            status=status.HTTP_409_CONFLICT,
        )
    action = None
    step = None
    batch = None
    if task.action == RpaTask.Action.REJECTION_NOTICE:
        payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        action = (
            ConversationAction.objects.select_for_update()
            .filter(
                pk=payload.get("conversation_action_id"),
                application_id=target.get("application_id"),
                approval_id=task.approval_id,
                batch_id=task.execution_batch_id,
            )
            .first()
        )
        if action is None or not action.step_id or not action.batch_id:
            return Response({"detail": "未通过通知执行快照无效"}, status=status.HTTP_409_CONFLICT)
        step = StepExecution.objects.select_for_update().filter(
            pk=action.step_id,
            batch_id=action.batch_id,
        ).first()
        batch = ExecutionBatch.objects.select_for_update().filter(pk=action.batch_id).first()
        if step is None or batch is None:
            return Response({"detail": "未通过通知执行快照无效"}, status=status.HTTP_409_CONFLICT)
    if task.status == RpaTask.Status.LEASED:
        task.status = RpaTask.Status.RUNNING
        task.started_at = now
    task.lease_expires_at = now + timedelta(seconds=120)
    task.save(update_fields=["status", "started_at", "lease_expires_at", "updated_at"])
    if action is not None:
        if action.status == ConversationAction.Status.PENDING:
            action.status = ConversationAction.Status.RUNNING
            action.save(update_fields=["status", "updated_at"])
        if step.status == StepExecution.Status.PENDING:
            step.status = StepExecution.Status.RUNNING
            step.started_at = step.started_at or now
            step.save(update_fields=["status", "started_at", "updated_at"])
        if batch.status == ExecutionBatch.Status.PENDING:
            batch.status = ExecutionBatch.Status.RUNNING
            batch.save(update_fields=["status", "updated_at"])
    event_name = str(request.data.get("event", "progress"))[:64]
    if task.action == RpaTask.Action.REJECTION_NOTICE:
        event_message = "本机 Worker 正在执行未通过通知任务"
        event_data = {"status": task.status}
    else:
        event_message = str(request.data.get("message", ""))[:500]
        event_data = request.data.get("data") if isinstance(request.data.get("data"), dict) else {}
    event = append_event(
        task=task,
        event=event_name,
        message=event_message,
        data=event_data,
        level=str(request.data.get("level", "info"))[:16],
    )
    return Response({"id": event.id}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([HasRpaWorkerToken])
@serialize_sqlite_lifecycle
@transaction.atomic
def task_control_view(request, task_id):
    _, task, assignment = _lock_task_for_worker(request, task_id)
    if task is None or assignment != "assigned":
        return Response({"detail": "任务不存在或不属于该 Worker"}, status=status.HTTP_404_NOT_FOUND)
    return Response({
        "status": task.status,
        "cancel_requested": task.status == RpaTask.Status.CANCEL_REQUESTED,
    })


@api_view(["POST"])
@permission_classes([HasRpaWorkerToken])
@serialize_sqlite_lifecycle
@transaction.atomic
def complete_task_view(request, task_id):
    _, task, assignment = _lock_task_for_worker(request, task_id)
    if task is None:
        return Response({"detail": "任务不存在或不属于该 Worker"}, status=status.HTTP_404_NOT_FOUND)
    if assignment != "assigned":
        return Response({"detail": "任务租约已转移，旧 Worker 不得提交结果"}, status=status.HTTP_409_CONFLICT)
    if task.status == RpaTask.Status.CANCEL_REQUESTED:
        task.status = RpaTask.Status.CANCELLED
        task.result = {}
        task.error_code = "cancelled_by_user"
        task.error_message = "任务已按用户要求停止"
        task.completed_at = timezone.now()
        task.lease_expires_at = None
        task.save(update_fields=[
            "status", "result", "error_code", "error_message", "completed_at",
            "lease_expires_at", "updated_at",
        ])
        append_event(task=task, event="cancelled", message="本机 Worker 已停止当前任务")
        account = task.boss_account
        account.status = BossAccount.Status.READY
        account.save(update_fields=["status", "updated_at"])
        RecruitmentAuditLog.objects.create(
            boss_account=account,
            action="task_cancelled",
            target_id=str(task.pk),
            detail={"worker_key": task.worker.key if task.worker_id else ""},
        )
        _schedule_workflow_resume(task)
        return Response({"id": str(task.pk), "status": task.status})
    if task.status not in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}:
        return Response({"detail": "任务已结束"}, status=status.HTTP_409_CONFLICT)
    if task.lease_expires_at is None or task.lease_expires_at <= timezone.now():
        return Response({"detail": "任务租约已过期，Worker 不得提交结果"}, status=status.HTTP_409_CONFLICT)
    terminal = {RpaTask.Status.WAITING_HUMAN, RpaTask.Status.SUCCEEDED, RpaTask.Status.FAILED}
    completed_status = request.data.get("status")
    if completed_status not in terminal:
        return Response({"detail": "任务完成状态无效"}, status=status.HTTP_400_BAD_REQUEST)
    result = request.data.get("result") if isinstance(request.data.get("result"), dict) else {}
    completion_error_code = str(request.data.get("error_code", ""))[:64]
    completion_error_message = str(request.data.get("error_message", ""))[:2000]
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
    if task.action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
        campaign = SearchCampaign.objects.select_for_update().filter(
            pk=task.request_payload.get("campaign_id"), boss_account=task.boss_account,
        ).first()
        if campaign is None:
            _fail_orphaned_search_pull_task(task=task)
            return Response({
                "id": str(task.pk),
                "status": task.status,
                "error_code": task.error_code,
            })
        if completed_status in {RpaTask.Status.SUCCEEDED, RpaTask.Status.WAITING_HUMAN}:
            context = None
            validation_failed = True
            try:
                context = _validate_search_pull_result(task=task, campaign=campaign, result=result)
                validation_failed = False
                from recruitment.services.automation_plans import plan_fence_is_current

                completion_stopped = (
                    result.get("checkpoint_stopped") is True
                    or not plan_fence_is_current(
                        revision_id=task.automation_plan_revision_id,
                        generation=task.automation_generation,
                    )
                )
                if completed_status == RpaTask.Status.SUCCEEDED or completion_stopped:
                    _complete_search_pull_success(
                        task=task,
                        campaign=campaign,
                        context=context,
                        user_stopped=completion_stopped,
                    )
                else:
                    _complete_search_pull_waiting_human(
                        task=task,
                        campaign=campaign,
                        context=context,
                        error_code=completion_error_code,
                        error_message=completion_error_message,
                    )
            except Exception as exc:
                if context is None and isinstance(exc, SearchPullResultError):
                    context = exc.evidence_context
                _fail_search_pull_completion(
                    task=task,
                    campaign=campaign,
                    error_message=exc,
                    context=context,
                    failure_code=(
                        "search_pull_result_invalid"
                        if validation_failed
                        else "search_pull_persist_failed"
                    ),
                )
                return Response({
                    "id": str(task.pk),
                    "status": task.status,
                    "error_code": task.error_code,
                })
            return Response({"id": str(task.pk), "status": task.status})
        else:
            _fail_search_pull_completion(
                task=task,
                campaign=campaign,
                error_message=completion_error_message or "Worker 报告主动寻访失败",
                failure_code="worker_reported_failure",
            )
            return Response({
                "id": str(task.pk),
                "status": task.status,
                "error_code": task.error_code,
            })
    if task.action == RpaTask.Action.SYNC_CONVERSATIONS and completed_status == RpaTask.Status.SUCCEEDED:
        rows = result.get("conversations")
        sync_checkpoint_stopped = result.get("checkpoint_stopped") is True
        cleanup_paths = set()
        if isinstance(rows, list):
            for cleanup_row in rows:
                if not isinstance(cleanup_row, dict):
                    continue
                attachments = cleanup_row.get("attachments")
                if not isinstance(attachments, list):
                    continue
                for attachment in attachments:
                    if not isinstance(attachment, dict):
                        continue
                    resolved = _safe_incoming_path(attachment.get("path"), suffix=".pdf")
                    if resolved is not None:
                        cleanup_paths.add(resolved)
        # A stopped or unmatched job must not leave downloaded applicant PII behind.
        for cleanup_path in cleanup_paths:
            transaction.on_commit(lambda path=cleanup_path: path.unlink(missing_ok=True))
        try:
            scoped_plans = _valid_passive_scope_plans(task)
            unscoped_manual_sync = scoped_plans is None
            server_scope_stopped = scoped_plans is not None and not scoped_plans
            scope_stopped = sync_checkpoint_stopped or server_scope_stopped
            valid_plans = {} if scope_stopped else (scoped_plans or {})
            allowed_job_ids = None if unscoped_manual_sync and not scope_stopped else list(valid_plans)
            payload = task.request_payload if isinstance(task.request_payload, dict) else {}
            selected_job_id = payload.get("job")
            if scoped_plans is None and selected_job_id:
                selected_job = RecruitmentJob.objects.filter(
                    pk=selected_job_id,
                    boss_account=task.boss_account,
                ).first()
                if selected_job is None:
                    return Response(
                        {"detail": "消息同步缺少有效的所选岗位"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                allowed_job_ids = [selected_job.pk]
            sync_result = sync_conversation_states(
                account=task.boss_account,
                rows=rows,
                actor=task.created_by,
                allowed_job_ids=allowed_job_ids,
            )
            archived = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                application = JobApplication.objects.filter(
                    pk=row.get("application_id"),
                    job__boss_account=task.boss_account,
                ).first()
                if application is None:
                    continue
                if allowed_job_ids is not None and application.job_id not in allowed_job_ids:
                    continue
                messages = [dict(item) for item in row.get("messages", []) if isinstance(item, dict)]
                attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
                if attachments:
                    target_message = next(
                        (item for item in reversed(messages) if item.get("direction") == "candidate"),
                        None,
                    )
                    if target_message is not None:
                        target_message["attachments"] = [
                            {
                                "external_id": str(item.get("external_id", "")),
                                "filename": str(item.get("filename", "附件简历.pdf")),
                                "content_type": "application/pdf",
                                "file_size": int(item.get("file_size", 0) or 0),
                                "path": str(item.get("path", "")),
                            }
                            for item in attachments
                            if isinstance(item, dict)
                        ]
                ingest_conversation(
                    application=application,
                    account=task.boss_account,
                    messages=messages,
                    cursor=str(row.get("cursor", "")),
                )
                for attachment in row.get("attachments") if isinstance(row.get("attachments"), list) else []:
                    if not isinstance(attachment, dict):
                        continue
                    try:
                        resolved = _safe_incoming_path(attachment.get("path"), suffix=".pdf")
                        if resolved is None:
                            continue
                        resume, created = archive_pdf(
                            application=application,
                            filename=attachment.get("filename", "附件简历.pdf"),
                            content=resolved.read_bytes(),
                            source=Resume.Source.BOSS,
                            actor=task.created_by,
                        )
                        archived += int(created)
                        MessageAttachment.objects.filter(
                            message__conversation_state__application=application,
                            original_name=attachment.get("filename", "附件简历.pdf"),
                            archived_resume__isnull=True,
                        ).order_by("-created_at").update(archived_resume=resume)
                    except (OSError, ValueError):
                        continue
                if not task.request_payload.get("workflow_managed"):
                    if unscoped_manual_sync:
                        process_pending_messages(
                            application=application,
                            account=task.boss_account,
                            actor=task.created_by,
                            schedule_actions=True,
                            create_attentions=True,
                        )
                        continue
                    plan = valid_plans.get(application.job_id)
                    if plan is None:
                        continue
                    process_pending_messages(
                        application=application,
                        account=task.boss_account,
                        actor=task.created_by,
                        schedule_actions=True,
                        create_attentions=True,
                        automation_plan_revision=plan.current_revision,
                        automation_generation=plan.control_generation,
                        workflow_run=plan.current_run,
                    )
            recovered_approvals = 0
            for plan in valid_plans.values():
                recovered_approvals += recover_unfulfilled_resume_requests(
                    plan=plan,
                    actor=task.created_by,
                )
            sync_result["attachments_archived"] = archived
            sync_result["resume_approvals_recovered"] = recovered_approvals
            result = {"sync": sync_result}
            if scope_stopped:
                completed_status = RpaTask.Status.CANCELLED
                completion_error_code = "automation_plan_stopped"
                completion_error_message = "消息同步在安全检查点停止，未处理已停止岗位的数据"
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if task.action == RpaTask.Action.VIEW_ONLINE_RESUME and completed_status == RpaTask.Status.SUCCEEDED:
        raw_path = Path(str(result.get("image_path", "")))
        incoming = (Path(settings.MEDIA_ROOT) / "rpa-incoming").resolve()
        try:
            target = task.request_payload.get("target") if isinstance(task.request_payload.get("target"), dict) else {}
            approval = task.approval
            approved_payload = approval.payload if approval and isinstance(approval.payload, dict) else {}
            expected_external_id = str(target.get("external_id", "")).strip()
            if (
                approval is None
                or approval.action != AutomationApproval.Action.VIEW_ONLINE_RESUME
                or approval.status != AutomationApproval.Status.APPROVED
                or approved_payload != task.request_payload
                or task.idempotency_key != f"online-resume-task:{approval.pk}"
                or approval.rpa_tasks.exclude(pk=task.pk).exists()
                or result.get("verified") is not True
                or not expected_external_id
                or str(result.get("expected_external_id", "")).strip() != expected_external_id
                or str(result.get("observed_external_id", "")).strip() != expected_external_id
                or not target.get("fingerprint")
                or result.get("identity_fingerprint") != target.get("fingerprint")
            ):
                raise ValueError
            resolved = raw_path.resolve(strict=True)
            if incoming not in resolved.parents or resolved.suffix.lower() != ".png":
                raise ValueError
            application = JobApplication.objects.get(
                pk=task.request_payload.get("application_id"),
                job__boss_account=task.boss_account,
            )
            resume, created = archive_online_resume_image(
                application=application,
                filename=result.get("filename", "在线简历.png"),
                content=resolved.read_bytes(),
                external_id=expected_external_id,
                actor=task.created_by,
            )
            transaction.on_commit(lambda path=resolved: path.unlink(missing_ok=True))
            result = {
                "resume_id": resume.pk,
                "created": created,
                "verified": True,
                "expected_external_id": expected_external_id,
                "observed_external_id": expected_external_id,
            }
        except Exception:
            completed_status = RpaTask.Status.WAITING_HUMAN
            completion_error_code = "target_identity_unverifiable"
            completion_error_message = "在线简历回执缺少与批准快照一致的平台稳定 ID，未执行归档"
            result = {"verified": False, "identity_validation": "rejected"}
    communication_actions = {
        RpaTask.Action.GREET,
        RpaTask.Action.REQUEST_RESUME,
        RpaTask.Action.SEND_INTERVIEW,
        RpaTask.Action.REJECTION_NOTICE,
    }
    if task.action in communication_actions:
        complete_communication_task(
            task=task,
            status=completed_status,
            result=result,
            error_code=completion_error_code,
            error_message=completion_error_message,
        )
        effective_status = task.status
        append_event(task=task, event="completed", message="沟通任务执行结束", data={"status": effective_status})
        account = task.boss_account
        if effective_status == RpaTask.Status.WAITING_HUMAN:
            next_account_status = BossAccount.Status.PAUSED
        else:
            next_account_status = BossAccount.Status.READY
        _set_account_runtime_status(account, next_account_status)
        RecruitmentAuditLog.objects.create(
            boss_account=account,
            action="communication_task_completed",
            target_id=str(task.pk),
            detail={"status": effective_status, "error_code": task.error_code},
        )
        _schedule_workflow_resume(task)
        return Response({"id": str(task.pk), "status": task.status})
    task.status = completed_status
    task.result = result
    task.error_code = completion_error_code
    task.error_message = completion_error_message
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
    elif completed_status == RpaTask.Status.WAITING_HUMAN:
        account.status = BossAccount.Status.PAUSED
        account.save(update_fields=["status", "updated_at"])
    if not account.active or account.archived_at is not None:
        _set_account_runtime_status(account, BossAccount.Status.OFFLINE)
    RecruitmentAuditLog.objects.create(
        boss_account=account,
        action="task_completed",
        target_id=str(task.pk),
        detail={"status": completed_status, "error_code": task.error_code},
    )
    _schedule_workflow_resume(task)
    return Response({"id": str(task.pk), "status": task.status})
