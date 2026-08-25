import hashlib

from django.db import migrations
from django.utils import timezone


def bind_existing_task_snapshots(apps, schema_editor):
    AiProcessingTask = apps.get_model("recruitment", "AiProcessingTask")
    UserModelCredential = apps.get_model("accounts", "UserModelCredential")
    database = schema_editor.connection.alias
    now = timezone.now()

    snapshots = {}
    credentials = UserModelCredential.objects.using(database).values(
        "user_id", "api_url", "model", "encrypted_api_key"
    )
    for credential in credentials.iterator():
        api_url = str(credential["api_url"] or "").strip()
        model = str(credential["model"] or "").strip()
        encrypted_api_key = str(credential["encrypted_api_key"] or "")
        if not api_url or not model or not encrypted_api_key:
            continue
        fingerprint = hashlib.sha256(
            "\0".join((api_url, model, encrypted_api_key)).encode("utf-8")
        ).hexdigest()
        snapshots[credential["user_id"]] = (api_url, model, encrypted_api_key, fingerprint)

    active_statuses = {"waiting_config", "pending", "extracting", "ocr", "model"}
    processing_statuses = {"extracting", "ocr", "model"}
    recoverable_statuses = active_statuses | {"failed"}
    tasks = AiProcessingTask.objects.using(database).filter(status__in=recoverable_statuses)
    for task in tasks.iterator():
        snapshot = snapshots.get(task.requested_by_id)
        update_fields = ["updated_at"]
        task.updated_at = now
        if snapshot:
            (
                task.model_api_url_snapshot,
                task.model_name_snapshot,
                task.encrypted_model_api_key_snapshot,
                task.model_snapshot_fingerprint,
            ) = snapshot
            task.model_snapshot_bound_at = now
            update_fields.extend(
                [
                    "model_api_url_snapshot",
                    "model_name_snapshot",
                    "encrypted_model_api_key_snapshot",
                    "model_snapshot_fingerprint",
                    "model_snapshot_bound_at",
                ]
            )
            if task.status == "waiting_config" or task.status in processing_statuses:
                task.status = "pending"
                task.available_at = now
                task.leased_at = None
                task.lease_expires_at = None
                task.lease_token = None
                task.error_code = ""
                task.error_message = ""
                update_fields.extend(
                    [
                        "status",
                        "available_at",
                        "leased_at",
                        "lease_expires_at",
                        "lease_token",
                        "error_code",
                        "error_message",
                    ]
                )
        elif task.status in active_statuses:
            task.status = "waiting_config"
            task.leased_at = None
            task.lease_expires_at = None
            task.lease_token = None
            task.error_code = "model_not_configured"
            task.error_message = "等待该任务首次绑定可用的大模型配置"
            update_fields.extend(
                [
                    "status",
                    "leased_at",
                    "lease_expires_at",
                    "lease_token",
                    "error_code",
                    "error_message",
                ]
            )
        task.save(using=database, update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_repair_partial_model_profiles"),
        ("recruitment", "0025_aiprocessingtask_model_snapshot"),
    ]

    operations = [
        migrations.RunPython(bind_existing_task_snapshots, migrations.RunPython.noop),
    ]
