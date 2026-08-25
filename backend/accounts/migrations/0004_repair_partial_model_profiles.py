from django.db import migrations


def _is_complete(record):
    return bool(
        str(record.api_url or "").strip()
        and str(record.model or "").strip()
        and str(record.encrypted_api_key or "").strip()
    )


def repair_partial_model_profiles(apps, schema_editor):
    credential_model = apps.get_model("accounts", "UserModelCredential")
    profile_model = apps.get_model("accounts", "UserModelProfile")
    user_ids = set(credential_model.objects.values_list("user_id", flat=True))
    user_ids.update(profile_model.objects.values_list("user_id", flat=True))

    for user_id in user_ids:
        active = profile_model.objects.filter(user_id=user_id, is_active=True).first()
        if active is not None and not _is_complete(active):
            active.is_active = False
            active.save(update_fields=["is_active", "updated_at"])
            active = None
        if active is None:
            credential_model.objects.filter(user_id=user_id).delete()
            continue
        credential_model.objects.update_or_create(
            user_id=user_id,
            defaults={
                "api_url": active.api_url,
                "model": active.model,
                "encrypted_api_key": active.encrypted_api_key,
                "key_last4": active.key_last4,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_expand_model_api_urls"),
    ]

    operations = [
        migrations.RunPython(repair_partial_model_profiles, migrations.RunPython.noop),
    ]
