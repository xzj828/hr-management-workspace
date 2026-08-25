from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0024_automationevidence_task_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiprocessingtask",
            name="encrypted_model_api_key_snapshot",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="aiprocessingtask",
            name="model_api_url_snapshot",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="aiprocessingtask",
            name="model_name_snapshot",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="aiprocessingtask",
            name="model_snapshot_bound_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aiprocessingtask",
            name="model_snapshot_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddConstraint(
            model_name="aiprocessingtask",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        encrypted_model_api_key_snapshot="",
                        model_api_url_snapshot="",
                        model_name_snapshot="",
                        model_snapshot_bound_at__isnull=True,
                        model_snapshot_fingerprint="",
                    )
                    | (
                        ~models.Q(model_api_url_snapshot="")
                        & ~models.Q(model_name_snapshot="")
                        & ~models.Q(encrypted_model_api_key_snapshot="")
                        & ~models.Q(model_snapshot_fingerprint="")
                        & models.Q(model_snapshot_bound_at__isnull=False)
                    )
                ),
                name="ai_task_model_snapshot_state",
            ),
        ),
    ]
