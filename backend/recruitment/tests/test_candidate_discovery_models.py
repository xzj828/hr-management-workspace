from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from recruitment.models import (
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    RecruitmentJob,
)


class CandidateDiscoveryModelTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user("discovery_hr")
        self.account = BossAccount.objects.create(
            name="BOSS 发现账号",
            browser_profile="boss-discovery",
            cdp_port=53470,
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-discovery",
            title="前端工程师",
            owner=self.hr,
        )

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

    def test_same_account_job_fingerprint_is_unique(self):
        self.discovery()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.discovery(source="search")

    def test_same_fingerprint_can_be_discovered_for_another_job(self):
        self.discovery()
        another = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-product",
            title="产品经理",
            owner=self.hr,
        )

        result = self.discovery(job=another, source="search")

        self.assertEqual(result.job, another)

    def test_external_identity_cannot_bind_two_candidates(self):
        first = Candidate.objects.create(identity_key="boss:1:first", name="林晓")
        second = Candidate.objects.create(identity_key="boss:1:second", name="林晓")
        CandidateExternalIdentity.objects.create(
            boss_account=self.account,
            candidate=first,
            fingerprint="e" * 64,
            identity_quality="fingerprint",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CandidateExternalIdentity.objects.create(
                    boss_account=self.account,
                    candidate=second,
                    fingerprint="e" * 64,
                    identity_quality="fingerprint",
                )
