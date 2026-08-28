import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0031_recruitmentautomationplan_archived_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="searchcampaign",
            name="analysis_failed_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="searchcampaign",
            name="qualified_resume_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="searchcampaign",
            name="standard",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="search_campaigns",
                to="recruitment.jobstandardversion",
            ),
        ),
        migrations.AlterField(
            model_name="searchcampaign",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "草稿"),
                    ("queued", "已排队"),
                    ("running", "运行中"),
                    ("analyzing", "AI 分析中"),
                    ("paused", "已暂停"),
                    ("succeeded", "已完成"),
                    ("failed", "失败"),
                    ("cancelled", "已取消"),
                ],
                db_index=True,
                default="draft",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="searchcampaign",
            name="stop_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "未停止"),
                    ("target_reached", "达到合格简历目标"),
                    ("scan_limit", "达到 AI 分析上限"),
                    ("candidates_exhausted", "候选简历不足"),
                    ("analysis_failed", "AI 分析失败"),
                    ("quota", "查看额度不足"),
                    ("paywall", "遇到付费墙"),
                    ("risk_control", "验证码或风控"),
                    ("account_offline", "账号离线"),
                    ("user_stopped", "人工停止"),
                    ("error", "执行异常"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="SearchCampaignItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("pending", "等待 AI 分析"), ("structuring", "简历结构化中"), ("scoring", "简历评分中"), ("waiting_config", "等待模型配置"), ("qualified", "AI 建议进一步沟通"), ("not_qualified", "AI 未建议进一步沟通"), ("failed", "AI 分析失败"), ("skipped", "达到目标后未分析")], db_index=True, default="pending", max_length=24)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("analyzed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="search_campaign_items", to="recruitment.jobapplication")),
                ("assessment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="search_campaign_items", to="recruitment.resumeassessment")),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="recruitment.searchcampaign")),
                ("resume", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="search_campaign_items", to="recruitment.resume")),
                ("score_task", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="search_campaign_score_items", to="recruitment.aiprocessingtask")),
                ("structure_task", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="search_campaign_structure_items", to="recruitment.aiprocessingtask")),
            ],
            options={"ordering": ["sequence", "id"]},
        ),
        migrations.AddConstraint(
            model_name="searchcampaignitem",
            constraint=models.UniqueConstraint(fields=("campaign", "resume"), name="unique_search_campaign_resume"),
        ),
        migrations.AddConstraint(
            model_name="searchcampaignitem",
            constraint=models.UniqueConstraint(fields=("campaign", "sequence"), name="unique_search_campaign_sequence"),
        ),
    ]
