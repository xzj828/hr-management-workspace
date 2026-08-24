from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0011_add_conversation_sync_action")]

    operations = [
        migrations.AddField(
            model_name="bossaccount",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="recruitmentjob",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="candidate",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="resume",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="workflowtemplate",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
