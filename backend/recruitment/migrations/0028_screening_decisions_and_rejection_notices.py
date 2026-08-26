import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0027_unique_active_check_status_task"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="executionbatch",
            name="quota_reserved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="executionbatch",
            name="reserved_amount",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="executionbatch",
            name="reserved_day",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="executionbatch",
            name="reserved_metric",
            field=models.CharField(blank=True, max_length=24),
        ),
        migrations.AlterField(
            model_name="automationapproval",
            name="action",
            field=models.CharField(
                choices=[
                    ("sync_positions", "同步职位"),
                    ("greet", "打招呼"),
                    ("request_resume", "索要简历"),
                    ("view_online_resume", "查看在线简历"),
                    ("send_interview", "发送面试邀约"),
                    ("rejection_notice", "发送简历未通过通知"),
                    ("deep_match", "深度匹配"),
                    ("search_pull_resumes", "搜索并拉取在线简历"),
                ],
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="conversationaction",
            name="action",
            field=models.CharField(
                choices=[
                    ("greet", "打招呼"),
                    ("request_resume", "索要简历"),
                    ("send_interview", "发送面试邀约"),
                    ("rejection_notice", "简历未通过通知"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="rpatask",
            name="action",
            field=models.CharField(
                choices=[
                    ("check_status", "检查状态"),
                    ("sync_positions", "同步职位"),
                    ("recommend_candidates", "推荐候选人"),
                    ("search_candidates", "搜索候选人"),
                    ("greet", "打招呼"),
                    ("request_resume", "索要简历"),
                    ("view_online_resume", "查看在线简历"),
                    ("send_interview", "发送面试邀约"),
                    ("rejection_notice", "发送简历未通过通知"),
                    ("deep_match", "深度匹配"),
                    ("sync_conversations", "同步沟通状态"),
                    ("search_pull_resumes", "搜索并拉取在线简历"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="ScreeningDecisionBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("request_id", models.UUIDField(editable=False, unique=True)),
                ("decision", models.CharField(choices=[("pass", "通过"), ("fail", "未通过")], max_length=12)),
                ("reason", models.TextField()),
                ("payload_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_screening_decision_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="screening_decision_batches",
                        to="recruitment.recruitmentjob",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ApplicationScreeningDecision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("decision", models.CharField(choices=[("pass", "通过"), ("fail", "未通过")], max_length=12)),
                ("reason", models.TextField()),
                ("version", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="screening_decisions",
                        to="recruitment.jobapplication",
                    ),
                ),
                (
                    "assessment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="screening_decisions",
                        to="recruitment.resumeassessment",
                    ),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="decisions",
                        to="recruitment.screeningdecisionbatch",
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="screening_decisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resume",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="screening_decisions",
                        to="recruitment.resume",
                    ),
                ),
            ],
            options={
                "ordering": ["-version", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("application", "version"),
                        name="unique_application_screening_decision_version",
                    ),
                    models.UniqueConstraint(
                        fields=("batch", "application"),
                        name="unique_screening_batch_application",
                    ),
                ],
            },
        ),
    ]
