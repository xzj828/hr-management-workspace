from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from . import worker_api

router = DefaultRouter()
router.register("boss-accounts", views.BossAccountViewSet, basename="boss-account")
router.register("jobs", views.RecruitmentJobViewSet, basename="recruitment-job")
router.register("job-documents", views.JobRequirementDocumentViewSet, basename="job-document")
router.register("job-document-versions", views.JobRequirementDocumentVersionViewSet, basename="job-document-version")
router.register("job-standards", views.JobStandardVersionViewSet, basename="job-standard")
router.register("message-sync-policies", views.MessageSyncPolicyViewSet, basename="message-sync-policy")
router.register("human-attentions", views.HumanAttentionViewSet, basename="human-attention")
router.register("candidates", views.CandidateViewSet, basename="candidate")
router.register("candidate-discoveries", views.CandidateDiscoveryViewSet, basename="candidate-discovery")
router.register("automation-approvals", views.AutomationApprovalViewSet, basename="automation-approval")
router.register("communication-actions", views.ConversationActionViewSet, basename="communication-action")
router.register("execution-batches", views.ExecutionBatchViewSet, basename="execution-batch")
router.register("workflows", views.WorkflowTemplateViewSet, basename="workflow")
router.register("workflow-versions", views.WorkflowVersionViewSet, basename="workflow-version")
router.register("workflow-runs", views.WorkflowRunViewSet, basename="workflow-run")
router.register("applications", views.JobApplicationViewSet, basename="job-application")
router.register("resumes", views.ResumeViewSet, basename="resume")
router.register("structured-resumes", views.StructuredResumeVersionViewSet, basename="structured-resume")
router.register("resume-assessments", views.ResumeAssessmentViewSet, basename="resume-assessment")
router.register("ai-tasks", views.AiProcessingTaskViewSet, basename="ai-task")
router.register("search-campaigns", views.SearchCampaignViewSet, basename="search-campaign")
router.register("rpa-tasks", views.RpaTaskViewSet, basename="rpa-task")

urlpatterns = [
    path("dashboard/", views.dashboard_view),
    path("demo-data/", views.demo_data_view),
    path("automation/summary/", views.automation_summary_view),
    path("worker/heartbeat/", worker_api.heartbeat_view),
    path("worker/status-targets/", worker_api.status_targets_view),
    path("worker/status-observations/", worker_api.status_observations_view),
    path("worker/tasks/lease/", worker_api.lease_task_view),
    path("worker/tasks/<uuid:task_id>/event/", worker_api.task_event_view),
    path("worker/tasks/<uuid:task_id>/control/", worker_api.task_control_view),
    path("worker/tasks/<uuid:task_id>/complete/", worker_api.complete_task_view),
    path("", include(router.urls)),
]
