from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("boss-accounts", views.BossAccountViewSet, basename="boss-account")
router.register("jobs", views.RecruitmentJobViewSet, basename="recruitment-job")
router.register("candidates", views.CandidateViewSet, basename="candidate")
router.register("applications", views.JobApplicationViewSet, basename="job-application")

urlpatterns = [
    path("dashboard/", views.dashboard_view),
    path("", include(router.urls)),
]
