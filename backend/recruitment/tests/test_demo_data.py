from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from recruitment.demo_data import clear_demo_data, demo_status, load_demo_data
from recruitment.models import Candidate, JobApplication, RecruitmentJob, Resume


class DemoDataServiceTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.override.enable()
        self.hr = User.objects.create_user(username="demo-owner")

    def tearDown(self):
        self.override.disable()
        self.temp_media.cleanup()

    def test_load_creates_exact_counts_and_real_pdfs(self):
        result = load_demo_data(self.hr)

        self.assertEqual(result, {"jobs": 3, "candidates": 10, "applications": 10, "resumes": 3})
        self.assertEqual(RecruitmentJob.objects.filter(is_demo=True).count(), 3)
        self.assertEqual(Candidate.objects.filter(is_demo=True).count(), 10)
        self.assertEqual(JobApplication.objects.filter(is_demo=True).count(), 10)
        self.assertEqual(Resume.objects.filter(is_demo=True).count(), 3)
        for resume in Resume.objects.filter(is_demo=True):
            self.assertTrue(Path(resume.file.path).read_bytes().startswith(b"%PDF"))

    def test_load_is_idempotent(self):
        load_demo_data(self.hr)
        first_files = set(Resume.objects.filter(is_demo=True).values_list("file", flat=True))

        load_demo_data(self.hr)

        self.assertEqual(
            demo_status()["counts"],
            {"jobs": 3, "candidates": 10, "applications": 10, "resumes": 3},
        )
        self.assertEqual(
            set(Resume.objects.filter(is_demo=True).values_list("file", flat=True)),
            first_files,
        )

    def test_clear_removes_only_demo_rows_and_files(self):
        real = Candidate.objects.create(identity_key="real:1", name="真实候选人")
        load_demo_data(self.hr)
        paths = [Path(item.file.path) for item in Resume.objects.filter(is_demo=True)]

        with self.captureOnCommitCallbacks(execute=True):
            result = clear_demo_data()

        self.assertEqual(
            result,
            {"loaded": False, "counts": {"jobs": 0, "candidates": 0, "applications": 0, "resumes": 0}},
        )
        self.assertTrue(Candidate.objects.filter(pk=real.pk).exists())
        self.assertFalse(Candidate.objects.filter(is_demo=True).exists())
        self.assertTrue(all(not path.exists() for path in paths))

    @patch("recruitment.demo_data.build_resume_pdf")
    def test_pdf_failure_rolls_back_rows_and_files(self, build_pdf):
        build_pdf.side_effect = [b"%PDF-1.4\nmock", RuntimeError("pdf failed")]

        with self.assertRaisesMessage(RuntimeError, "pdf failed"):
            load_demo_data(self.hr)

        self.assertFalse(RecruitmentJob.objects.filter(is_demo=True).exists())
        self.assertFalse(Candidate.objects.filter(is_demo=True).exists())
        self.assertFalse(JobApplication.objects.filter(is_demo=True).exists())
        self.assertFalse(Resume.objects.filter(is_demo=True).exists())
        self.assertEqual(list(Path(self.temp_media.name).rglob("*.pdf")), [])
