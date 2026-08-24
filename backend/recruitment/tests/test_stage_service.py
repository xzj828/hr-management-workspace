from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from recruitment.models import ApplicationStageHistory, Candidate, JobApplication, RecruitmentJob
from recruitment.services.stages import advance_for_event, change_stage_manually


class StageServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hr-stage")
        self.job = RecruitmentJob.objects.create(external_id="job-stage", title="运营", owner=self.user)
        candidate = Candidate.objects.create(identity_key="stage-candidate", name="周青")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")

    def test_verified_event_advances_and_audits_stage(self):
        changed = advance_for_event(application=self.application, event="greet_succeeded", actor=self.user)
        self.assertTrue(changed)
        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, JobApplication.Stage.GREETED)
        self.assertEqual(self.application.stage_history.get().source, ApplicationStageHistory.Source.AUTOMATION)

    def test_failed_or_uncertain_event_does_not_advance(self):
        changed = advance_for_event(
            application=self.application, event="greet_succeeded", actor=self.user, verified=False
        )
        self.assertFalse(changed)
        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, JobApplication.Stage.NEW)

    def test_manual_stage_change_requires_reason(self):
        with self.assertRaises(ValidationError):
            change_stage_manually(
                application=self.application,
                to_stage=JobApplication.Stage.REJECTED,
                actor=self.user,
                reason="",
            )

