from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from recruitment.models import AutomationUsage


LIMIT_FIELDS = {
    AutomationUsage.Metric.SEARCH: "daily_search_limit",
    AutomationUsage.Metric.DEEP_MATCH: "daily_search_limit",
    AutomationUsage.Metric.RESUME_VIEW: "daily_resume_view_limit",
    AutomationUsage.Metric.CONTACT: "daily_contact_limit",
    AutomationUsage.Metric.MESSAGE: "daily_message_limit",
}


@transaction.atomic
def consume(*, account, metric, amount=1):
    if metric not in LIMIT_FIELDS:
        raise ValidationError("不支持的自动化用量类型")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValidationError("用量必须是正整数")

    usage, _ = AutomationUsage.objects.select_for_update().get_or_create(
        boss_account=account,
        day=timezone.localdate(),
        metric=metric,
    )
    limit = getattr(account, LIMIT_FIELDS[metric])
    if limit > 0 and usage.used + amount > limit:
        raise ValidationError("该 BOSS 账号今日自动化用量已达上限")
    usage.used += amount
    usage.save(update_fields=["used"])
    return usage
