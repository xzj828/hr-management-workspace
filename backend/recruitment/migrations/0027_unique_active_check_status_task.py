from django.db import migrations, models
from django.db.models import Q


def collapse_duplicate_active_checks(apps, schema_editor):
    RpaTask = apps.get_model("recruitment", "RpaTask")
    groups = (
        RpaTask.objects.filter(
            action="check_status",
            status__in=["pending", "leased", "running"],
        )
        .values("boss_account_id")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for group in groups.iterator():
        tasks = list(
            RpaTask.objects.filter(
                boss_account_id=group["boss_account_id"],
                action="check_status",
                status__in=["pending", "leased", "running"],
            ).order_by("created_at", "pk")
        )
        for duplicate in tasks[1:]:
            duplicate.status = "cancelled"
            duplicate.error_code = "duplicate_active_check_status"
            duplicate.error_message = "迁移时取消的重复账号状态任务"
            duplicate.save(update_fields=["status", "error_code", "error_message", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0026_bind_existing_ai_task_model_snapshots")]

    operations = [
        migrations.RunPython(collapse_duplicate_active_checks, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="rpatask",
            constraint=models.UniqueConstraint(
                fields=("boss_account", "action"),
                condition=Q(action="check_status", status__in=["pending", "leased", "running"]),
                name="unique_active_check_status_per_account",
            ),
        ),
    ]
