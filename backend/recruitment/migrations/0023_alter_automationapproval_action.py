from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0022_aiprocessingtask_lease_token"),
    ]

    operations = [
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
                    ("deep_match", "深度匹配"),
                    ("search_pull_resumes", "搜索并拉取在线简历"),
                ],
                max_length=40,
            ),
        ),
    ]
