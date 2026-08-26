from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from attendance.models import AccountProfile
from recruitment.models import (
    BossAccount, Candidate, JobApplication, RecruitmentJob, Resume, RpaTask,
    WorkflowEdge, WorkflowNode, WorkflowTemplate, WorkflowVersion,
    WorkflowRun,
)


class RecruitmentLifecycleApiTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="lifecycle-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.other = User.objects.create_user(username="lifecycle-other")
        AccountProfile.objects.create(user=self.other, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="生命周期账号", browser_profile="lifecycle-account", cdp_port=53550,
        )
        self.account.authorized_users.add(self.hr)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="lifecycle-job", title="生命周期职位", owner=self.hr,
        )
        self.candidate = Candidate.objects.create(identity_key="lifecycle-candidate", name="候选人甲")
        self.application = JobApplication.objects.create(
            candidate=self.candidate, job=self.job, source="boss",
        )
        self.resume = Resume.objects.create(
            candidate=self.candidate, application=self.application, original_name="候选人甲.pdf",
            file="recruitment/resumes/lifecycle.pdf", file_size=128,
        )
        self.template = WorkflowTemplate.objects.create(name="可删除流程", created_by=self.hr)
        self.version = WorkflowVersion.objects.create(template=self.template, version=1, boss_account=self.account, created_by=self.hr)
        source = WorkflowNode.objects.create(version=self.version, node_key="source", node_type="search")
        end = WorkflowNode.objects.create(version=self.version, node_key="end", node_type="end")
        WorkflowEdge.objects.create(version=self.version, source=source, target=end)
        self.client = APIClient()
        self.client.force_login(self.hr)

    def test_account_with_active_task_is_blocked_then_can_be_archived_and_restored(self):
        task = RpaTask.objects.create(
            boss_account=self.account, action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.RUNNING, created_by=self.hr,
        )

        blocked = self.client.post(f"/api/recruitment/boss-accounts/{self.account.id}/archive/")
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertIn("任务", blocked.data["detail"])

        task.status = RpaTask.Status.FAILED
        task.save(update_fields=["status"])
        archived = self.client.post(f"/api/recruitment/boss-accounts/{self.account.id}/archive/")

        self.assertEqual(archived.status_code, 200, archived.data)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.archived_at)
        self.assertFalse(self.account.active)
        self.assertEqual(self.client.get("/api/recruitment/boss-accounts/").data["count"], 0)
        self.assertEqual(self.client.get("/api/recruitment/boss-accounts/?archived=1").data["count"], 1)

        restored = self.client.post(f"/api/recruitment/boss-accounts/{self.account.id}/restore/?archived=1")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.archived_at)
        self.assertTrue(self.account.active)

    def test_jobs_candidates_and_resumes_are_reversibly_archived(self):
        targets = [
            ("jobs", self.job),
            ("candidates", self.candidate),
            ("resumes", self.resume),
        ]

        for resource, instance in targets:
            response = self.client.post(f"/api/recruitment/{resource}/{instance.pk}/archive/")
            self.assertEqual(response.status_code, 200, response.data)
            instance.refresh_from_db()
            self.assertIsNotNone(instance.archived_at)
            restored = self.client.post(f"/api/recruitment/{resource}/{instance.pk}/restore/?archived=1")
            self.assertEqual(restored.status_code, 200, restored.data)
            instance.refresh_from_db()
            self.assertIsNone(instance.archived_at)

    def test_terminal_task_can_be_archived_but_active_task_cannot(self):
        task = RpaTask.objects.create(
            boss_account=self.account, action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.PENDING, created_by=self.hr,
        )

        blocked = self.client.post(f"/api/recruitment/rpa-tasks/{task.pk}/archive/")
        self.assertEqual(blocked.status_code, 409, blocked.data)

        task.status = RpaTask.Status.CANCELLED
        task.save(update_fields=["status"])
        archived = self.client.post(f"/api/recruitment/rpa-tasks/{task.pk}/archive/")
        self.assertEqual(archived.status_code, 200, archived.data)
        task.refresh_from_db()
        self.assertIsNotNone(task.archived_at)

    def test_draft_workflow_version_can_be_deleted_but_enabled_version_cannot(self):
        deleted = self.client.delete(f"/api/recruitment/workflow-versions/{self.version.pk}/")
        self.assertEqual(deleted.status_code, 204, getattr(deleted, "data", None))
        self.assertFalse(WorkflowVersion.objects.filter(pk=self.version.pk).exists())

        protected_template = WorkflowTemplate.objects.create(name="已启用流程", created_by=self.hr)
        enabled = WorkflowVersion.objects.create(
            template=protected_template, version=1, status=WorkflowVersion.Status.ENABLED,
            boss_account=self.account, created_by=self.hr,
        )
        protected_template.active_version = enabled
        protected_template.save(update_fields=["active_version"])

        blocked = self.client.delete(f"/api/recruitment/workflow-versions/{enabled.pk}/")
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertTrue(WorkflowVersion.objects.filter(pk=enabled.pk).exists())

    def test_draft_workflow_version_with_run_returns_conflict_instead_of_protected_error(self):
        WorkflowRun.objects.create(
            version=self.version,
            boss_account=self.account,
            actor=self.hr,
            mode=WorkflowRun.Mode.DRY_RUN,
            idempotency_key="lifecycle-draft-run",
        )

        response = self.client.delete(f"/api/recruitment/workflow-versions/{self.version.pk}/")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("运行记录", response.data["detail"])
        self.assertTrue(WorkflowVersion.objects.filter(pk=self.version.pk).exists())

    def test_audited_resources_do_not_expose_physical_delete(self):
        for resource, instance in (
            ("boss-accounts", self.account),
            ("jobs", self.job),
            ("workflows", self.template),
        ):
            response = self.client.delete(f"/api/recruitment/{resource}/{instance.pk}/")
            self.assertEqual(response.status_code, 405, getattr(response, "data", None))

    def test_archived_at_cannot_be_forged_through_regular_patch(self):
        for resource, instance in (
            ("boss-accounts", self.account),
            ("jobs", self.job),
            ("workflows", self.template),
        ):
            response = self.client.patch(
                f"/api/recruitment/{resource}/{instance.pk}/",
                {"archived_at": "2026-08-25T12:00:00Z"},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
            instance.refresh_from_db()
            self.assertIsNone(instance.archived_at)

    def test_other_hr_cannot_archive_objects_outside_their_scope(self):
        self.client.force_login(self.other)

        response = self.client.post(f"/api/recruitment/boss-accounts/{self.account.pk}/archive/")

        self.assertEqual(response.status_code, 404)
