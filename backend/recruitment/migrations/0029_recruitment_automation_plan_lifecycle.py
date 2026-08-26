import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("recruitment", "0028_screening_decisions_and_rejection_notices"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecruitmentAutomationPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("passive_resume", "被动咨询与简历获取"),
                            ("active_resume_search", "主动搜索并拉取简历"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "desired_state",
                    models.CharField(
                        choices=[("running", "运行中"), ("paused", "已暂停"), ("stopped", "已停止")],
                        db_index=True,
                        default="stopped",
                        max_length=16,
                    ),
                ),
                ("control_version", models.PositiveIntegerField(default=0)),
                ("control_generation", models.PositiveIntegerField(default=0)),
                ("last_control_request_id", models.UUIDField(blank=True, null=True)),
                ("last_control_action", models.CharField(blank=True, max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_recruitment_automation_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="automation_plans",
                        to="recruitment.recruitmentjob",
                    ),
                ),
                (
                    "managed_template",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="managed_automation_plans",
                        to="recruitment.workflowtemplate",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_recruitment_automation_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["job_id", "kind"]},
        ),
        migrations.AddConstraint(
            model_name="recruitmentautomationplan",
            constraint=models.UniqueConstraint(fields=("job",), name="unique_job_automation_plan"),
        ),
        migrations.CreateModel(
            name="RecruitmentAutomationPlanRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("passive_resume", "被动咨询与简历获取"),
                            ("active_resume_search", "主动搜索并拉取简历"),
                        ],
                        max_length=32,
                    ),
                ),
                ("request_id", models.UUIDField(unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("config_snapshot", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recruitment_automation_plan_revisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="recruitment.recruitmentautomationplan",
                    ),
                ),
                (
                    "workflow_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="automation_plan_revisions",
                        to="recruitment.workflowversion",
                    ),
                ),
            ],
            options={"ordering": ["-revision", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="recruitmentautomationplanrevision",
            constraint=models.UniqueConstraint(fields=("plan", "revision"), name="unique_automation_plan_revision"),
        ),
        migrations.AddField(
            model_name="recruitmentautomationplan",
            name="current_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="current_for_plans",
                to="recruitment.recruitmentautomationplanrevision",
            ),
        ),
        migrations.AddField(
            model_name="recruitmentautomationplan",
            name="current_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="current_for_automation_plans",
                to="recruitment.workflowrun",
            ),
        ),
        migrations.AddField(
            model_name="workflowrun",
            name="automation_plan_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_runs",
                to="recruitment.recruitmentautomationplanrevision",
            ),
        ),
        migrations.AddField(
            model_name="workflowrun",
            name="automation_generation",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="automation_plan_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rpa_tasks",
                to="recruitment.recruitmentautomationplanrevision",
            ),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="automation_generation",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="lease_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="lease_generation",
            field=models.PositiveIntegerField(default=0),
        ),
        *[
            migrations.AddField(
                model_name=model_name,
                name="automation_plan_revision",
                field=models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name=related_name,
                    to="recruitment.recruitmentautomationplanrevision",
                ),
            )
            for model_name, related_name in [
                ("automationapproval", "automation_approvals"),
                ("executionbatch", "execution_batches"),
                ("conversationaction", "conversation_actions"),
                ("humanattention", "human_attentions"),
                ("searchcampaign", "search_campaigns"),
            ]
        ],
        *[
            migrations.AddField(
                model_name=model_name,
                name="automation_generation",
                field=models.PositiveIntegerField(blank=True, null=True),
            )
            for model_name in [
                "automationapproval",
                "executionbatch",
                "conversationaction",
                "humanattention",
                "searchcampaign",
            ]
        ],
    ]
