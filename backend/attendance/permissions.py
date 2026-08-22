from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import AccountProfile


def user_role(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return AccountProfile.Role.ADMIN
    profile, _ = AccountProfile.objects.get_or_create(user=user)
    return profile.role


def is_hr_user(user):
    return user_role(user) in {AccountProfile.Role.ADMIN, AccountProfile.Role.HR}


class HRWritePermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return is_hr_user(request.user)


class HRPermission(BasePermission):
    def has_permission(self, request, view):
        return is_hr_user(request.user)

