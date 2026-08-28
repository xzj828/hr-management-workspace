from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0032_search_campaign_ai_qualification"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowrun",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
