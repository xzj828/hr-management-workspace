import hashlib
import json
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from recruitment.models import (
    BossAccount,
    ConversationAction,
    ConversationMessage,
    ConversationSyncState,
    JobApplication,
    MessageAttachment,
    RecruitmentAutomationPlan,
    RecruitmentJob,
)
from recruitment.services.human_attention import ensure_attention
from recruitment.services.message_intent import MessageIntent, classify_candidate_message
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle


@dataclass(frozen=True)
class ConversationIngestionResult:
    created_messages: int
    created_attachments: int
    cursor: str


@dataclass(frozen=True)
class ConversationDecision:
    intent: MessageIntent
    message: ConversationMessage | None = None
    attention: object | None = None


def _sent_at(value):
    parsed = parse_datetime(str(value or ""))
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _fingerprint(item):
    normalized = {
        "direction": str(item.get("direction", "")),
        "content": " ".join(str(item.get("content", "")).split()),
        "sent_at": str(item.get("sent_at", "")),
        "attachments": [
            {
                "external_id": str(value.get("external_id", "")),
                "filename": str(value.get("filename", "")),
            }
            for value in item.get("attachments", [])
            if isinstance(value, dict)
        ],
    }
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@transaction.atomic
def ingest_conversation(*, application, account, messages, cursor=""):
    if application.job.boss_account_id != account.pk:
        raise ValueError("候选人不属于当前 BOSS 账号")
    if not isinstance(messages, list):
        raise ValueError("消息结果必须是数组")
    state, _ = ConversationSyncState.objects.select_for_update().get_or_create(
        application=application,
        defaults={"boss_account": account},
    )
    if state.boss_account_id != account.pk:
        raise ValueError("会话同步账号不一致")

    created_messages = 0
    created_attachments = 0
    created_candidate_messages = []
    last_preview = state.last_message_preview
    has_candidate_reply = state.has_candidate_reply
    for item in messages:
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction", ""))
        if direction not in ConversationMessage.Direction.values:
            continue
        external_id = str(item.get("external_id", ""))[:200]
        fingerprint = _fingerprint(item)
        lookup = {"conversation_state": state, "external_id": external_id} if external_id else {
            "conversation_state": state,
            "fingerprint": fingerprint,
        }
        message, created = ConversationMessage.objects.get_or_create(
            **lookup,
            defaults={
                "external_id": external_id,
                "fingerprint": fingerprint,
                "direction": direction,
                "content": str(item.get("content", "")),
                "sent_at": _sent_at(item.get("sent_at")),
                "raw_payload": item,
            },
        )
        if not created:
            continue
        created_messages += 1
        if direction == ConversationMessage.Direction.CANDIDATE:
            created_candidate_messages.append(message)
        last_preview = message.content[:500]
        has_candidate_reply = has_candidate_reply or direction == ConversationMessage.Direction.CANDIDATE
        for attachment in item.get("attachments", []):
            if not isinstance(attachment, dict):
                continue
            MessageAttachment.objects.create(
                message=message,
                external_id=str(attachment.get("external_id", ""))[:200],
                original_name=str(attachment.get("filename", "附件"))[:255],
                content_type=str(attachment.get("content_type", ""))[:100],
                file_size=max(0, int(attachment.get("file_size", 0) or 0)),
                sha256=str(attachment.get("sha256", ""))[:64],
                source_payload=attachment,
            )
            created_attachments += 1

    state.cursor = str(cursor or state.cursor)[:300]
    state.last_message_preview = last_preview
    state.has_candidate_reply = has_candidate_reply
    state.last_synced_at = timezone.now()
    state.save(
        update_fields=["cursor", "last_message_preview", "has_candidate_reply", "last_synced_at", "updated_at"]
    )
    cached_state = application._state.fields_cache.get("conversation_state")
    if cached_state is not None and cached_state.pk == state.pk:
        cached_state.cursor = state.cursor
        cached_state.last_message_preview = state.last_message_preview
        cached_state.has_candidate_reply = state.has_candidate_reply
        cached_state.last_synced_at = state.last_synced_at
    if created_candidate_messages:
        from recruitment.services.workflow_events import publish_workflow_event

        for candidate_message in created_candidate_messages:
            transaction.on_commit(
                lambda item=candidate_message: publish_workflow_event(
                    event="candidate_message.received",
                    application=application,
                    event_key=f"message:{item.pk}",
                    payload={"message_id": item.pk},
                )
            )
    return ConversationIngestionResult(created_messages, created_attachments, state.cursor)


@serialize_sqlite_lifecycle
@transaction.atomic
def _queue_resume_request(
    *,
    application,
    account,
    actor,
    message,
    first_contact,
    source_message,
    automation_plan_revision=None,
    automation_generation=None,
):
    from recruitment.services.communications import _identity_snapshot, prepare_communication

    plan_revision_id = getattr(automation_plan_revision, "pk", automation_plan_revision)
    if plan_revision_id is not None:
        # Linearize the callback with stop/restart.  Whichever transaction gets
        # Account -> Plan first either creates a cancellable old-generation
        # draft before stop, or observes the closed fence and does nothing.
        account = BossAccount.objects.select_for_update().get(pk=account.pk)
        plan = RecruitmentAutomationPlan.objects.select_for_update().filter(
            revisions__pk=plan_revision_id,
        ).first()
        if (
            plan is None
            or plan.current_revision_id != plan_revision_id
            or plan.control_generation != automation_generation
            or plan.desired_state != RecruitmentAutomationPlan.DesiredState.RUNNING
            or plan.job_id != application.job_id
            or plan.job.boss_account_id != account.pk
            or plan.job.archived_at is not None
            or plan.job.status != RecruitmentJob.Status.OPEN
            or not account.active
            or account.archived_at is not None
        ):
            return None

    target = _identity_snapshot(application, account)
    if not target.get("external_id") and not target.get("fingerprint"):
        ensure_attention(
            attention_type="identity_ambiguous",
            title=f"{application.candidate.name} 缺少可验证的 BOSS 身份",
            idempotency_key=f"resume-request-identity:{source_message.pk}",
            account=account,
            job=application.job,
            application=application,
            detail={"message_id": source_message.pk},
            priority=20,
        )
        return None
    try:
        return prepare_communication(
            account=account,
            applications=[application],
            action=ConversationAction.Action.REQUEST_RESUME,
            message=message,
            actor=actor,
            request_id=(
                f"auto-request-resume:{application.pk}:{source_message.pk}:"
                f"{getattr(automation_plan_revision, 'pk', automation_plan_revision) or 0}:"
                f"{automation_generation or 0}"
            ),
            item_contexts={
                application.pk: {
                    "first_contact": first_contact,
                    "source_message_id": source_message.pk,
                }
            },
            automation_plan_revision=automation_plan_revision,
            automation_generation=automation_generation,
        )
    except (PermissionDenied, ValidationError) as exc:
        ensure_attention(
            attention_type="resume_request_failed",
            title=f"{application.candidate.name} 自动求简历未能排队",
            idempotency_key=f"resume-request-failed:{source_message.pk}",
            account=account,
            job=application.job,
            application=application,
            detail={"message_id": source_message.pk, "error": str(exc)},
            priority=20,
        )
        return None


@transaction.atomic
def process_pending_messages(
    *,
    application,
    account,
    actor=None,
    schedule_actions=False,
    create_attentions=True,
    automation_plan_revision=None,
    automation_generation=None,
    workflow_run=None,
):
    state = ConversationSyncState.objects.select_for_update().filter(
        application=application,
        boss_account=account,
    ).first()
    if state is None:
        return ConversationDecision(MessageIntent.IGNORE)
    pending = list(
        state.messages.select_for_update()
        .filter(processed_at__isnull=True)
        .prefetch_related("attachments")
        .order_by("sent_at", "id")
    )
    candidate_messages = [item for item in pending if item.direction == ConversationMessage.Direction.CANDIDATE]
    if not candidate_messages:
        if pending:
            state.messages.filter(pk__in=[item.pk for item in pending]).update(processed_at=timezone.now())
        return ConversationDecision(MessageIntent.IGNORE)

    has_resume = application.resumes.filter(archived_at__isnull=True).exists() or state.messages.filter(
        attachments__original_name__iendswith=".pdf"
    ).exists()
    latest = candidate_messages[-1]
    intent = classify_candidate_message(latest.content, has_resume_attachment=has_resume)
    attention = None
    if intent == MessageIntent.OBSERVING and create_attentions:
        attention, _ = ensure_attention(
            attention_type="observing_candidate",
            title=f"{application.candidate.name} 希望进一步了解公司或岗位",
            idempotency_key=f"observing-message:{latest.pk}",
            account=account,
            job=application.job,
            application=application,
            workflow_run=workflow_run,
            automation_plan_revision=automation_plan_revision,
            automation_generation=automation_generation,
            detail={"message_id": latest.pk, "message": latest.content},
            priority=10,
        )

    now = timezone.now()
    state.messages.filter(pk__in=[item.pk for item in pending]).update(processed_at=now)
    raw = dict(latest.raw_payload)
    raw["intent"] = str(intent)
    latest.raw_payload = raw
    latest.processed_at = now
    latest.save(update_fields=["raw_payload", "processed_at"])
    if schedule_actions and actor is not None and intent == MessageIntent.REQUEST_RESUME:
        first_contact = not state.messages.filter(direction=ConversationMessage.Direction.HR).exists()
        transaction.on_commit(
            lambda: _queue_resume_request(
                application=application,
                account=account,
                actor=actor,
                message="您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？",
                first_contact=first_contact,
                source_message=latest,
                automation_plan_revision=automation_plan_revision,
                automation_generation=automation_generation,
            )
        )
    return ConversationDecision(intent=intent, message=latest, attention=attention)


@serialize_sqlite_lifecycle
@transaction.atomic
def recover_unfulfilled_resume_requests(
    *,
    plan,
    actor,
):
    """Recreate current-generation approvals for processed replies that never reached execution."""
    locked_plan = (
        RecruitmentAutomationPlan.objects.select_for_update()
        .select_related("job__boss_account", "current_revision")
        .filter(pk=plan.pk)
        .first()
    )
    if (
        locked_plan is None
        or locked_plan.kind != RecruitmentAutomationPlan.Kind.PASSIVE_RESUME
        or locked_plan.desired_state != RecruitmentAutomationPlan.DesiredState.RUNNING
        or locked_plan.current_revision_id is None
        or locked_plan.job.archived_at is not None
        or locked_plan.job.status != RecruitmentJob.Status.OPEN
        or not locked_plan.job.boss_account.active
        or locked_plan.job.boss_account.archived_at is not None
    ):
        return 0

    now = timezone.now()
    blocking_statuses = [
        ConversationAction.Status.APPROVED,
        ConversationAction.Status.PENDING,
        ConversationAction.Status.RUNNING,
        ConversationAction.Status.WAITING_HUMAN,
        ConversationAction.Status.SUCCEEDED,
    ]
    applications = (
        JobApplication.objects.select_for_update()
        .select_related("candidate", "job")
        .filter(
            job=locked_plan.job,
            archived_at__isnull=True,
            conversation_state__isnull=False,
        )
        .order_by("id")
    )
    recovered = 0
    for application in applications:
        if application.resumes.filter(archived_at__isnull=True).exists():
            continue
        effective_action_exists = ConversationAction.objects.filter(
            application=application,
            action=ConversationAction.Action.REQUEST_RESUME,
        ).filter(
            Q(status__in=blocking_statuses)
            | Q(
                status=ConversationAction.Status.DRAFT,
                approval__status="draft",
                approval__expires_at__gt=now,
            )
        ).exists()
        if effective_action_exists:
            continue

        state = application.conversation_state
        latest_candidate_message = (
            state.messages.filter(
                direction=ConversationMessage.Direction.CANDIDATE,
                processed_at__isnull=False,
            )
            .order_by("sent_at", "id")
            .last()
        )
        if latest_candidate_message is None:
            continue
        payload = latest_candidate_message.raw_payload
        if not isinstance(payload, dict) or payload.get("intent") != str(MessageIntent.REQUEST_RESUME):
            continue
        first_contact = not state.messages.filter(direction=ConversationMessage.Direction.HR).exists()
        approval = _queue_resume_request(
            application=application,
            account=locked_plan.job.boss_account,
            actor=actor,
            message=(
                locked_plan.current_revision.config_snapshot.get("reply_message")
                or "您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？"
            ),
            first_contact=first_contact,
            source_message=latest_candidate_message,
            automation_plan_revision=locked_plan.current_revision,
            automation_generation=locked_plan.control_generation,
        )
        recovered += int(
            approval is not None
            and approval.status == "draft"
            and approval.automation_plan_revision_id == locked_plan.current_revision_id
            and approval.automation_generation == locked_plan.control_generation
        )
    return recovered
