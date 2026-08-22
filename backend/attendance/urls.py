from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register("policies", views.AttendancePolicyViewSet, basename="policy")
router.register("tags", views.EmployeeTagViewSet, basename="tag")
router.register("employees", views.EmployeeViewSet, basename="employee")
router.register("imports", views.ImportBatchViewSet, basename="import")
router.register("results", views.AttendanceResultViewSet, basename="result")
router.register("raw-days", views.RawPunchDayViewSet, basename="raw-day")
router.register("suspicions", views.CrossDaySuspicionViewSet, basename="suspicion")

urlpatterns = [
    path("auth/csrf/", views.csrf_view),
    path("auth/login/", views.login_view),
    path("auth/logout/", views.logout_view),
    path("auth/me/", views.me_view),
    path("dashboard/", views.dashboard_view),
    path("", include(router.urls)),
]

