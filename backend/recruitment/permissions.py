from rest_framework.permissions import SAFE_METHODS, BasePermission

from attendance.permissions import is_hr_user


class RecruitmentWritePermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return is_hr_user(request.user)
