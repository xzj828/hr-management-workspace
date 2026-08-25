import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from recruitment.management.commands.run_rpa_worker import execute_search_pull_resumes
from recruitment.rpa.cli import CliAccountConfig


class FakeRunner:
    def __init__(self, source_path):
        self.source_path = source_path
        self.previewed = []

    def search(self, account, keyword):
        return [
            {"display_name": "陈月", "current_title": "Python", "city": "北京"},
            {"display_name": "林河", "current_title": "Django", "city": "上海"},
        ]

    def preview(self, account, name):
        self.previewed.append(name)
        return SimpleNamespace(stdout=f"简历预览截图：{self.source_path}\n")


class SearchPullWorkerTests(SimpleTestCase):
    def test_searches_and_copies_target_number_of_cli_resume_images(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            media = Path(root) / "media"
            runner = FakeRunner(source)
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            task = {"request_payload": {
                "source": "search", "criteria": {"keyword": "Python"},
                "target_resume_count": 1, "max_scan_count": 2,
            }}
            with override_settings(MEDIA_ROOT=media):
                outcome = execute_search_pull_resumes(task, account, runner)

            self.assertEqual(outcome["status"], "succeeded")
            self.assertEqual(outcome["result"]["scanned_count"], 2)
            self.assertEqual(len(outcome["result"]["resumes"]), 1)
            self.assertEqual(runner.previewed, ["陈月"])
            self.assertTrue(Path(outcome["result"]["resumes"][0]["path"]).exists())
