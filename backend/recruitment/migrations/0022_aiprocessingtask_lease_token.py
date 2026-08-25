from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0021_resume_intelligence")]
    operations = [
        migrations.AddField(
            model_name="aiprocessingtask",
            name="lease_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
    ]
