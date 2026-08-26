from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        (
            "recruitment",
            "0028_remove_rpatask_unique_active_rpa_task_per_account_and_more",
        ),
        ("recruitment", "0029_recruitment_automation_plan_lifecycle"),
    ]

    operations = []
