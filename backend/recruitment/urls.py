from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from . import worker_api

router = DefaultRouter()
router.register("boss-accounts", views.BossAccountViewSet, basename="boss-account")
router.register("jobs", views.RecruitmentJobViewSet, basename="recruitment-job")
router.register("candidates", views.CandidateViewSet, basename="candidate")
router.register("applications", views.JobApplicationViewSet, basename="job-application")
router.register("rpa-tasks", views.RpaTaskViewSet, basename="rpa-task")

urlpatterns = [
    path("dashboard/", views.dashboard_view),
    path("automation/summary/", views.automation_summary_view),
    path("worker/heartbeat/", worker_api.heartbeat_view),
    path("worker/tasks/lease/", worker_api.lease_task_view),
    path("worker/tasks/<uuid:task_id>/event/", worker_api.task_event_view),
    path("worker/tasks/<uuid:task_id>/complete/", worker_api.complete_task_view),
    path("", include(router.urls)),
]
