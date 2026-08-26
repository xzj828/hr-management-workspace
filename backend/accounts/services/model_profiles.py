from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from accounts.crypto import encrypt_secret
from accounts.models import UserModelCredential, UserModelProfile


MIN_API_KEY_LENGTH = 8
MAX_API_KEY_LENGTH = 4096


class ModelProfileConflict(ValueError):
    """模型档案写入与现有唯一状态冲突。"""


class ModelProfileInvalid(ValueError):
    """模型档案不满足激活或兼容投影要求。"""


def _lock_user(user):
    return get_user_model().objects.select_for_update().get(pk=user.pk)


def _is_complete(profile) -> bool:
    return bool(
        str(profile.api_url or "").strip()
        and str(profile.model or "").strip()
        and profile.encrypted_api_key
    )


def _assert_complete(profile):
    if not _is_complete(profile):
        raise ModelProfileInvalid("模型档案缺少 API 地址、模型名称或 API Key，暂不能切换")


def _validated_api_key(value, *, missing_message):
    api_key = str(value or "").strip()
    if not api_key:
        raise ModelProfileInvalid(missing_message)
    if len(api_key) < MIN_API_KEY_LENGTH:
        raise ModelProfileInvalid(f"API Key 至少需要 {MIN_API_KEY_LENGTH} 个字符")
    if len(api_key) > MAX_API_KEY_LENGTH:
        raise ModelProfileInvalid(f"API Key 不能超过 {MAX_API_KEY_LENGTH} 个字符")
    return api_key


def _sync_projection_locked(profile):
    credential, created = UserModelCredential.objects.select_for_update().get_or_create(user=profile.user)
    projected = {
        "api_url": profile.api_url,
        "model": profile.model,
        "encrypted_api_key": profile.encrypted_api_key,
        "key_last4": profile.key_last4,
    }
    changed = created or any(getattr(credential, field) != value for field, value in projected.items())
    if changed:
        for field, value in projected.items():
            setattr(credential, field, value)
        credential.save()
    return credential


def _activate_locked(profile):
    _assert_complete(profile)
    UserModelProfile.objects.filter(user=profile.user, is_active=True).exclude(pk=profile.pk).update(
        is_active=False
    )
    if not profile.is_active:
        profile.is_active = True
        profile.save(update_fields=["is_active", "updated_at"])
    _sync_projection_locked(profile)
    return profile


def _assert_unique_name(*, user, name, exclude_id=None):
    queryset = UserModelProfile.objects.filter(user=user, name__iexact=name)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        raise ModelProfileConflict("当前账号已存在同名模型配置")


def create_model_profile(*, user, values):
    try:
        with transaction.atomic():
            locked_user = _lock_user(user)
            data = dict(values)
            api_key = _validated_api_key(
                data.pop("api_key", ""),
                missing_message="新增模型档案必须填写 API Key",
            )
            make_active = bool(data.pop("make_active", False))
            name = str(data.get("name") or "").strip()
            _assert_unique_name(user=locked_user, name=name)
            has_active = UserModelProfile.objects.filter(user=locked_user, is_active=True).exists()
            profile = UserModelProfile.objects.create(
                user=locked_user,
                name=name,
                api_url=str(data.get("api_url") or "").strip(),
                model=str(data.get("model") or "").strip(),
                encrypted_api_key=encrypt_secret(api_key),
                key_last4=api_key[-4:],
                is_active=False,
            )
            if make_active or not has_active:
                _activate_locked(profile)
            return profile
    except IntegrityError as exc:
        raise ModelProfileConflict("模型配置名称重复，或当前账号已有活动模型") from exc


def update_model_profile(*, user, profile, values):
    try:
        with transaction.atomic():
            locked_user = _lock_user(user)
            locked = UserModelProfile.objects.select_for_update().get(pk=profile.pk, user=locked_user)
            data = dict(values)
            data.pop("make_active", None)
            api_key = data.pop("api_key", None)
            if "name" in data:
                data["name"] = str(data["name"] or "").strip()
                _assert_unique_name(user=locked_user, name=data["name"], exclude_id=locked.pk)
            for field in ("name", "api_url", "model"):
                if field in data:
                    setattr(locked, field, str(data[field] or "").strip())
            if api_key is not None:
                api_key = _validated_api_key(api_key, missing_message="API Key 不能为空")
                locked.encrypted_api_key = encrypt_secret(api_key)
                locked.key_last4 = api_key[-4:]
            locked.save()
            if locked.is_active:
                _assert_complete(locked)
                _sync_projection_locked(locked)
            return locked
    except IntegrityError as exc:
        raise ModelProfileConflict("当前账号已存在同名模型配置") from exc


@transaction.atomic
def activate_model_profile(*, user, profile):
    locked_user = _lock_user(user)
    locked = UserModelProfile.objects.select_for_update().get(pk=profile.pk, user=locked_user)
    return _activate_locked(locked)


@transaction.atomic
def delete_model_profile(*, user, profile):
    """Permanently erase one owned model profile and its encrypted secret.

    Deleting the active profile deliberately leaves the user without an active
    projection. Choosing a different profile is an explicit user action; tasks
    that already captured an immutable model snapshot are unaffected.
    """
    locked_user = _lock_user(user)
    locked = UserModelProfile.objects.select_for_update().get(pk=profile.pk, user=locked_user)
    was_active = locked.is_active
    locked.delete()
    if was_active:
        UserModelCredential.objects.filter(user=locked_user).delete()
    return was_active


def _legacy_profile_name(*, user, model):
    base = (str(model or "").strip() or "默认模型")[:80]
    if not UserModelProfile.objects.filter(user=user, name__iexact=base).exists():
        return base
    for suffix in range(2, 1000):
        suffix_text = f" {suffix}"
        candidate = f"{base[:80 - len(suffix_text)]}{suffix_text}"
        if not UserModelProfile.objects.filter(user=user, name__iexact=candidate).exists():
            return candidate
    raise ModelProfileConflict("无法为旧模型配置分配唯一名称")


@transaction.atomic
def update_legacy_model_credential(*, user, values):
    locked_user = _lock_user(user)
    credential = UserModelCredential.objects.select_for_update().filter(user=locked_user).first()
    data = dict(values)
    api_key = data.pop("api_key", None)
    candidate = UserModelCredential(
        user=locked_user,
        api_url=str(data.get("api_url", credential.api_url if credential else "") or "").strip(),
        model=str(data.get("model", credential.model if credential else "") or "").strip(),
        encrypted_api_key=credential.encrypted_api_key if credential else "",
        key_last4=credential.key_last4 if credential else "",
    )
    if api_key is not None:
        api_key = _validated_api_key(api_key, missing_message="API Key 不能为空")
        candidate.encrypted_api_key = encrypt_secret(api_key)
        candidate.key_last4 = api_key[-4:]
    _assert_complete(candidate)

    if credential is None:
        credential = UserModelCredential(user=locked_user)
    credential.api_url = candidate.api_url
    credential.model = candidate.model
    credential.encrypted_api_key = candidate.encrypted_api_key
    credential.key_last4 = candidate.key_last4
    credential.save()

    active = UserModelProfile.objects.select_for_update().filter(user=locked_user, is_active=True).first()
    if active:
        active.api_url = credential.api_url
        active.model = credential.model
        active.encrypted_api_key = credential.encrypted_api_key
        active.key_last4 = credential.key_last4
        active.save()
    elif _is_complete(credential):
        UserModelProfile.objects.create(
            user=locked_user,
            name=_legacy_profile_name(user=locked_user, model=credential.model),
            api_url=credential.api_url,
            model=credential.model,
            encrypted_api_key=credential.encrypted_api_key,
            key_last4=credential.key_last4,
            is_active=True,
        )
    return credential


@transaction.atomic
def get_legacy_model_credential(*, user):
    locked_user = _lock_user(user)
    active = UserModelProfile.objects.select_for_update().filter(user=locked_user, is_active=True).first()
    if active:
        return _sync_projection_locked(active)
    credential, _ = UserModelCredential.objects.select_for_update().get_or_create(user=locked_user)
    return credential


@transaction.atomic
def clear_legacy_model_credential(*, user):
    locked_user = _lock_user(user)
    UserModelProfile.objects.select_for_update().filter(user=locked_user, is_active=True).delete()
    UserModelCredential.objects.filter(user=locked_user).delete()
