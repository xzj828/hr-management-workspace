from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from recruitment.models import (
    BossAccount,
    Candidate,
    FileTextExtraction,
    JobApplication,
    JobStandardVersion,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    RpaTask,
    SearchCampaign,
    SearchCampaignItem,
    StructuredResumeVersion,
    WorkflowNodeRun,
)
from recruitment.services.search_campaign_intelligence import reconcile_search_campaign
from recruitment.services.workflow_nodes import _search_campaign_outcome


class SearchCampaignIntelligenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("campaign-ai")
        self.account = BossAccount.objects.create(name="AI campaign", browser_profile="ai", cdp_port=54100)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="ai-job",
            title="AI 工程师",
            owner=self.user,
        )
        self.standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status=JobStandardVersion.Status.PUBLISHED,
            criteria={"dimensions": [{"key": "fit", "name": "岗位匹配", "weight": 100, "description": "匹配程度"}]},
            created_by=self.user,
            published_by=self.user,
            published_at=timezone.now(),
        )

    def make_item(self, campaign, sequence, *, recommendation=None):
        candidate = Candidate.objects.create(name=f"候选人{sequence}", identity_key=f"campaign-ai-{sequence}-{campaign.pk}")
        application = JobApplication.objects.create(candidate=candidate, job=self.job)
        resume = Resume.objects.create(
            candidate=candidate,
            application=application,
            original_name=f"resume-{sequence}.png",
            content_type="image/png",
            file_size=8,
            source=Resume.Source.BOSS_ONLINE,
            processing_status=Resume.ProcessingStatus.READY,
            sha256=f"{sequence:064d}",
            version=1,
        )
        item = SearchCampaignItem.objects.create(
            campaign=campaign,
            application=application,
            resume=resume,
            sequence=sequence,
        )
        if recommendation is not None:
            extraction = FileTextExtraction.objects.create(
                source_kind=FileTextExtraction.SourceKind.RESUME,
                source_id=resume.pk,
                source_sha256=resume.sha256,
                method=FileTextExtraction.Method.IMAGE_OCR,
                status=FileTextExtraction.Status.READY,
            )
            structure = StructuredResumeVersion.objects.create(
                resume=resume,
                version=1,
                extraction=extraction,
                data={},
                model_name="test-model",
            )
            assessment = ResumeAssessment.objects.create(
                structured_resume=structure,
                standard=self.standard,
                total_score=Decimal("80.00"),
                confidence=Decimal("0.800"),
                recommendation=recommendation,
                model_name="test-model",
            )
            return item, assessment
        return item, None

    def make_campaign(self, *, target=1, maximum=2):
        return SearchCampaign.objects.create(
            name="AI 主动寻访",
            boss_account=self.account,
            job=self.job,
            standard=self.standard,
            source=SearchCampaign.Source.SEARCH,
            status=SearchCampaign.Status.ANALYZING,
            target_resume_count=target,
            max_scan_count=maximum,
            created_by=self.user,
        )

    def test_stops_after_reaching_ai_qualified_target_and_skips_remaining_items(self):
        campaign = self.make_campaign(target=1, maximum=2)
        first, assessment = self.make_item(
            campaign,
            1,
            recommendation=ResumeAssessment.Recommendation.ADVANCE,
        )
        second, _ = self.make_item(campaign, 2)

        reconcile_search_campaign(campaign.pk)

        campaign.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.SUCCEEDED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.TARGET_REACHED)
        self.assertEqual(campaign.scanned_count, 1)
        self.assertEqual(campaign.qualified_resume_count, 1)
        self.assertEqual(first.assessment, assessment)
        self.assertEqual(first.status, SearchCampaignItem.Status.QUALIFIED)
        self.assertEqual(second.status, SearchCampaignItem.Status.SKIPPED)

    def test_reports_ai_scan_limit_when_all_analyzed_without_enough_qualified(self):
        campaign = self.make_campaign(target=2, maximum=2)
        self.make_item(campaign, 1, recommendation=ResumeAssessment.Recommendation.REVIEW)
        self.make_item(campaign, 2, recommendation=ResumeAssessment.Recommendation.HOLD)

        reconcile_search_campaign(campaign.pk)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.SUCCEEDED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.SCAN_LIMIT)
        self.assertEqual(campaign.scanned_count, 2)
        self.assertEqual(campaign.qualified_resume_count, 0)

    def test_pauses_when_next_ai_task_waits_for_model_configuration(self):
        campaign = self.make_campaign(target=1, maximum=1)
        item, _ = self.make_item(campaign, 1)

        reconcile_search_campaign(campaign.pk)

        campaign.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.PAUSED)
        self.assertEqual(item.status, SearchCampaignItem.Status.WAITING_CONFIG)
        self.assertEqual(item.structure_task.status, "waiting_config")
        self.assertIn("模型", campaign.error_message)

    def test_workflow_output_contains_only_ai_qualified_applications(self):
        campaign = self.make_campaign(target=1, maximum=2)
        qualified, _ = self.make_item(
            campaign,
            1,
            recommendation=ResumeAssessment.Recommendation.ADVANCE,
        )
        self.make_item(
            campaign,
            2,
            recommendation=ResumeAssessment.Recommendation.HOLD,
        )
        reconcile_search_campaign(campaign.pk)
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
            status=RpaTask.Status.SUCCEEDED,
            created_by=self.user,
        )
        campaign.refresh_from_db()

        status, output = _search_campaign_outcome(task, campaign)

        self.assertEqual(status, WorkflowNodeRun.Status.SUCCEEDED)
        self.assertEqual(output["application_ids"], [qualified.application_id])
