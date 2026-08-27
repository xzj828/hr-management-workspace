from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0030_merge_20260826_1700"),
    ]

    operations = [
        migrations.AddField(
            model_name="recruitmentautomationplan",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
