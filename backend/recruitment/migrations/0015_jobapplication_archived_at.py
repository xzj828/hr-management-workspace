from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0014_link_tasks_to_workflow_runs")]

    operations = [
        migrations.AddField(
            model_name="jobapplication",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
