from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_usermodelprofile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usermodelcredential",
            name="api_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AlterField(
            model_name="usermodelprofile",
            name="api_url",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
