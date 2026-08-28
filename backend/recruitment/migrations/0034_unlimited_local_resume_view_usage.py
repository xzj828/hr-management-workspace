from django.db import migrations, models


def remove_local_resume_view_caps(apps, schema_editor):
    BossAccount = apps.get_model("recruitment", "BossAccount")
    BossAccount.objects.update(daily_resume_view_limit=0)


def restore_previous_default_cap(apps, schema_editor):
    BossAccount = apps.get_model("recruitment", "BossAccount")
    BossAccount.objects.filter(daily_resume_view_limit=0).update(daily_resume_view_limit=20)


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0033_workflowrun_archived_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bossaccount",
            name="daily_resume_view_limit",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(remove_local_resume_view_caps, restore_previous_default_cap),
    ]
