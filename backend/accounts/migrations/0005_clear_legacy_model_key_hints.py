from django.db import migrations


def clear_legacy_model_key_hints(apps, schema_editor):
    credential_model = apps.get_model("accounts", "UserModelCredential")
    profile_model = apps.get_model("accounts", "UserModelProfile")
    # Historical writes accepted keys shorter than the four-character display
    # suffix. Their stored hint could therefore equal the entire secret.
    credential_model.objects.exclude(key_last4="").update(key_last4="")
    profile_model.objects.exclude(key_last4="").update(key_last4="")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_repair_partial_model_profiles"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_model_key_hints, migrations.RunPython.noop),
    ]
