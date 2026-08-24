from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from recruitment.models import (
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    JobApplication,
    RecruitmentJob,
)
from recruitment.services.discovery import import_discoveries, sync_discoveries


class DiscoveryServiceTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user("service_hr")
        self.account = BossAccount.objects.create(
            name="BOSS 服务账号",
            browser_profile="boss-service",
            cdp_port=53470,
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-service",
            title="前端工程师",
            owner=self.hr,
        )

    def row(self, **overrides):
        values = {
            "external_id": "",
            "identity_quality": "fingerprint",
            "display_name": "林晓",
            "current_title": "高级前端工程师",
            "city": "北京",
            "experience": "星云科技 前端工程师",
            "education": "本科",
            "advantage": "Vue / ToB",
            "tags": ["Vue", "ToB"],
            "contact_hint": "可打招呼",
        }
        values.update(overrides)
        return values

    def discovery(self, **overrides):
        values = {
            "boss_account": self.account,
            "job": self.job,
            "source": "recommend",
            "fingerprint": "f" * 64,
            "identity_quality": "fingerprint",
            "display_name": "林晓",
            "expires_at": timezone.now() + timedelta(days=7),
        }
        values.update(overrides)
        return CandidateDiscovery.objects.create(**values)

    def test_repeated_sync_updates_one_discovery(self):
        first = sync_discoveries(
            account=self.account,
            job=self.job,
            source="recommend",
            criteria={"job": "前端"},
            rows=[self.row(advantage="Vue")],
        )
        second = sync_discoveries(
            account=self.account,
            job=self.job,
            source="recommend",
            criteria={"job": "前端"},
            rows=[self.row(advantage="Vue 3")],
        )

        self.assertEqual(first.created, 1)
        self.assertEqual(second.updated, 1)
        self.assertEqual(CandidateDiscovery.objects.count(), 1)
        self.assertEqual(CandidateDiscovery.objects.get().advantage, "Vue 3")

    def test_same_name_different_fingerprint_stays_separate(self):
        first = self.discovery(fingerprint="a" * 64)
        second = self.discovery(fingerprint="b" * 64)

        result = import_discoveries(discoveries=[first, second], actor=self.hr)

        self.assertEqual(result.created_candidates, 2)
        self.assertEqual(Candidate.objects.filter(name="林晓").count(), 2)

    def test_reimport_reuses_candidate_and_application(self):
        first = self.discovery()
        initial = import_discoveries(discoveries=[first], actor=self.hr)
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-backend",
            title="后端工程师",
            owner=self.hr,
        )
        second = self.discovery(job=second_job, source="search")

        repeated = import_discoveries(discoveries=[first, second], actor=self.hr)

        self.assertEqual(initial.created_candidates, 1)
        self.assertEqual(repeated.created_candidates, 0)
        self.assertEqual(Candidate.objects.count(), 1)
        self.assertEqual(JobApplication.objects.count(), 2)
        self.assertEqual(CandidateExternalIdentity.objects.count(), 1)

    def test_platform_id_takes_identity_priority(self):
        synced = sync_discoveries(
            account=self.account,
            job=self.job,
            source="recommend",
            criteria={},
            rows=[self.row(external_id="geek-101", identity_quality="platform")],
        )
        discovery = CandidateDiscovery.objects.get()

        import_discoveries(discoveries=[discovery], actor=self.hr)

        self.assertEqual(synced.created, 1)
        self.assertEqual(Candidate.objects.get().identity_key, f"boss:{self.account.pk}:geek-101")
