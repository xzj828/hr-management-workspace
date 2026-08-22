from django.contrib.auth.models import User
from django.test import TestCase

from recruitment.models import BossAccount, RecruitmentJob
from recruitment.rpa.sync import sync_positions


class PositionSyncTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="position-owner")
        self.account = BossAccount.objects.create(
            name="职位同步账号",
            browser_profile="boss-sync-test",
            cdp_port=53470,
        )

    def test_sync_creates_then_updates_without_duplicates(self):
        first = sync_positions(account=self.account, owner=self.hr, rows=[{
            "external_id": "job-101", "title": "实施工程师", "status": "open", "raw": "first"
        }])
        job = RecruitmentJob.objects.get(boss_account=self.account, external_id="job-101")
        job.department = "交付部"
        job.headcount = 3
        job.save()
        second = sync_positions(account=self.account, owner=self.hr, rows=[{
            "external_id": "job-101", "title": "高级实施工程师", "status": "open", "raw": "second"
        }])

        self.assertEqual(first.created, 1)
        self.assertEqual(second.updated, 1)
        self.assertEqual(RecruitmentJob.objects.filter(boss_account=self.account).count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.title, "高级实施工程师")
        self.assertEqual(job.department, "交付部")
        self.assertEqual(job.headcount, 3)
        self.assertEqual(job.owner, self.hr)

    def test_unchanged_row_is_counted(self):
        rows = [{"external_id": "job-101", "title": "实施工程师", "status": "open", "raw": "same"}]
        sync_positions(account=self.account, owner=self.hr, rows=rows)

        summary = sync_positions(account=self.account, owner=self.hr, rows=rows)

        self.assertEqual(summary.unchanged, 1)
        self.assertEqual(summary.total, 1)

    def test_invalid_status_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "职位状态无效"):
            sync_positions(account=self.account, owner=self.hr, rows=[{
                "external_id": "job-101", "title": "实施工程师", "status": "deleted"
            }])

