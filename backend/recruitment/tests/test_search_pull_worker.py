import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from recruitment.management.commands.run_rpa_worker import execute_search_pull_resumes, execute_view_online_resume
from recruitment.rpa.cli import CliAccountConfig
from recruitment.services.discovery import _fingerprint


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
    def test_stop_before_first_search_checkpoint_never_calls_platform(self):
        runner = FakeRunner(Path("unused.png"))
        runner.search_calls = 0

        def search(account, keyword):
            runner.search_calls += 1
            return []

        runner.search = search
        task = {"request_payload": {
            "source": "search", "criteria": {"keyword": "Python"},
            "target_resume_count": 1, "max_scan_count": 2,
            "resume_view_budget": 2, "boss_account_id": 7,
        }}

        outcome = execute_search_pull_resumes(
            task,
            CliAccountConfig("edge", "profile", 53990),
            runner,
            checkpoint=lambda phase, sequence: False,
        )

        self.assertEqual(runner.search_calls, 0)
        self.assertEqual(outcome["result"]["scanned_count"], 0)
        self.assertTrue(outcome["result"]["checkpoint_stopped"])

    def test_stop_after_one_preview_preserves_one_atomic_result_and_starts_no_next_call(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            runner = FakeRunner(source)
            rows = [
                {"display_name": "陈月", "external_id": "stable-1", "current_title": "Python"},
                {"display_name": "林河", "external_id": "stable-2", "current_title": "Django"},
            ]
            runner.search = lambda account, keyword: rows
            runner.preview_by_external_id = lambda account, external_id: (
                runner.previewed.append(external_id)
                or SimpleNamespace(stdout=f"简历预览截图：{source}\n")
            )
            task = {"request_payload": {
                "source": "search", "criteria": {"keyword": "Python"},
                "target_resume_count": 2, "max_scan_count": 2,
                "resume_view_budget": 2, "boss_account_id": 7,
            }}

            def checkpoint(phase, sequence):
                return not (phase == "after_preview" and sequence == 1)

            with override_settings(MEDIA_ROOT=Path(root) / "media"):
                outcome = execute_search_pull_resumes(
                    task,
                    CliAccountConfig("edge", "profile", 53990),
                    runner,
                    checkpoint=checkpoint,
                )

            self.assertEqual(runner.previewed, ["stable-1"])
            self.assertEqual(len(outcome["result"]["resumes"]), 1)
            self.assertTrue(outcome["result"]["checkpoint_stopped"])

    def test_search_preserves_results_but_name_based_preview_waits_for_human(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            media = Path(root) / "media"
            runner = FakeRunner(source)
            runner.search = lambda account, keyword: [{
                "display_name": "陈月", "external_id": "boss-candidate-1",
                "current_title": "Python", "city": "北京",
            }]
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            task = {"request_payload": {
                "source": "search", "criteria": {"keyword": "Python"},
                "target_resume_count": 1, "max_scan_count": 2,
                "resume_view_budget": 2, "boss_account_id": 7,
            }}
            with override_settings(MEDIA_ROOT=media):
                outcome = execute_search_pull_resumes(task, account, runner)

            self.assertEqual(outcome["status"], "waiting_human")
            self.assertEqual(outcome["result"]["scanned_count"], 1)
            self.assertEqual(outcome["result"]["resumes"], [])
            self.assertEqual(runner.previewed, [])
            self.assertEqual(outcome["result"]["view_attempt_count"], 0)
            self.assertEqual(outcome["result"]["attempts"][0]["outcome"], "stable_action_unavailable")
            self.assertFalse(outcome["result"]["attempts"][0]["preview_attempted"])

    def test_stable_id_preview_contract_returns_expected_and_observed_ids(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            runner = FakeRunner(source)
            row = {
                "display_name": "陈月",
                "external_id": "boss-stable-1",
                "current_title": "Python",
                "city": "北京",
            }
            runner.search = lambda account, keyword: [row]

            def preview_by_external_id(account, external_id):
                runner.previewed.append(external_id)
                return SimpleNamespace(stdout=f"简历预览截图：{source}\n")

            runner.preview_by_external_id = preview_by_external_id
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            task = {"request_payload": {
                "source": "search", "criteria": {"keyword": "Python"},
                "target_resume_count": 1, "max_scan_count": 1,
                "resume_view_budget": 1, "boss_account_id": 7,
            }}

            with override_settings(MEDIA_ROOT=Path(root) / "media"):
                outcome = execute_search_pull_resumes(task, account, runner)

            self.assertEqual(outcome["status"], "succeeded")
            attempt = outcome["result"]["attempts"][0]
            self.assertEqual(attempt["expected_external_id"], row["external_id"])
            self.assertEqual(attempt["observed_external_id"], row["external_id"])
            self.assertEqual(attempt["sequence"], 1)
            self.assertTrue(attempt["timestamp"])
            identity = outcome["result"]["resumes"][0]["identity_snapshot"]
            self.assertEqual(identity["expected_external_id"], row["external_id"])
            self.assertEqual(identity["observed_external_id"], row["external_id"])
            self.assertEqual(runner.previewed, [row["external_id"]])

    def test_same_name_candidates_are_never_opened_by_display_name(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            runner = FakeRunner(source)
            runner.search = lambda account, keyword: [
                {"display_name": "陈月", "current_title": "Python", "city": "北京"},
                {"display_name": "陈月", "current_title": "Django", "city": "上海"},
            ]
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            task = {"request_payload": {
                "source": "search", "criteria": {"keyword": "Python"},
                "target_resume_count": 1, "max_scan_count": 2,
                "resume_view_budget": 2, "boss_account_id": 7,
            }}

            with override_settings(MEDIA_ROOT=Path(root) / "media"):
                outcome = execute_search_pull_resumes(task, account, runner)

            self.assertEqual(outcome["status"], "succeeded")
            self.assertEqual(outcome["result"]["resumes"], [])
            self.assertEqual(outcome["result"]["view_attempt_count"], 0)
            self.assertEqual(runner.previewed, [])
            self.assertTrue(all(
                attempt["outcome"] == "identity_ambiguous"
                for attempt in outcome["result"]["attempts"]
            ))

    def test_individual_online_resume_never_falls_back_to_name_based_preview(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            runner = FakeRunner(source)
            runner.search = lambda account, keyword: [{
                "display_name": "陈月", "external_id": "boss-candidate-1",
                "current_title": "Python", "city": "北京",
            }]
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            row = runner.search(account, "Python")[0]
            task = {"request_payload": {"target": {
                "boss_account_id": 7,
                "name": row["display_name"],
                "external_id": row["external_id"],
                "fingerprint": _fingerprint(7, row),
                "job_title": "Python 工程师",
                "verification": {"source": "search", "criteria": {"keyword": "Python"}},
            }}}

            with override_settings(MEDIA_ROOT=Path(root) / "media"):
                outcome = execute_view_online_resume(task, account, runner)

            self.assertEqual(outcome["status"], "waiting_human")
            self.assertEqual(outcome["error_code"], "stable_identity_action_unavailable")
            self.assertEqual(runner.previewed, [])

    def test_individual_stable_id_preview_returns_expected_and_observed_ids(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            runner = FakeRunner(source)
            row = {
                "display_name": "陈月", "external_id": "boss-stable-single",
                "current_title": "Python", "city": "北京",
            }
            runner.search = lambda account, keyword: [row]

            def preview_by_external_id(account, external_id):
                runner.previewed.append(external_id)
                return SimpleNamespace(stdout=f"简历预览截图：{source}\n")

            runner.preview_by_external_id = preview_by_external_id
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            task = {"request_payload": {"target": {
                "boss_account_id": 7,
                "name": row["display_name"],
                "external_id": row["external_id"],
                "fingerprint": _fingerprint(7, row),
                "job_title": "Python 工程师",
                "verification": {"source": "search", "criteria": {"keyword": "Python"}},
            }}}

            with override_settings(MEDIA_ROOT=Path(root) / "media"):
                outcome = execute_view_online_resume(task, account, runner)

            self.assertEqual(outcome["status"], "succeeded")
            self.assertEqual(outcome["result"]["expected_external_id"], row["external_id"])
            self.assertEqual(outcome["result"]["observed_external_id"], row["external_id"])
            self.assertEqual(runner.previewed, [row["external_id"]])

    def test_individual_online_resume_without_refreshable_identity_waits_for_human(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
            runner = FakeRunner(source)
            account = CliAccountConfig("edge", str(Path(root) / "profile"), 53990)
            task = {"request_payload": {"target": {
                "boss_account_id": 7,
                "name": "陈月",
                "fingerprint": "unverifiable",
                "job_title": "Python 工程师",
            }}}

            with override_settings(MEDIA_ROOT=Path(root) / "media"):
                outcome = execute_view_online_resume(task, account, runner)

            self.assertEqual(outcome["status"], "waiting_human")
            self.assertEqual(runner.previewed, [])
