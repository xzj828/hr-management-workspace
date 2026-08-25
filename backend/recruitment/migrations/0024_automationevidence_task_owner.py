from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0023_alter_automationapproval_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="automationevidence",
            name="step",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="evidence",
                to="recruitment.stepexecution",
            ),
        ),
        migrations.AddField(
            model_name="automationevidence",
            name="task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="automation_evidence",
                to="recruitment.rpatask",
            ),
        ),
        migrations.AddConstraint(
            model_name="automationevidence",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("step__isnull", False), ("task__isnull", True))
                    | models.Q(("step__isnull", True), ("task__isnull", False))
                ),
                name="evidence_has_exactly_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="automationevidence",
            constraint=models.UniqueConstraint(
                condition=models.Q(("task__isnull", False)),
                fields=("task", "kind"),
                name="unique_task_evidence_kind",
            ),
        ),
    ]
