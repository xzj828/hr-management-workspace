from django.test import SimpleTestCase

from recruitment.management.commands.run_rpa_worker import execute_greet, execute_request_resume, execute_send_interview
from recruitment.rpa.cli import CliAccountConfig


class FakeRunner:
    def __init__(self):
        self.calls = []

    def recommend(self, account, job):
        self.calls.append(("recommend", job))
        return [{"display_name": "林然", "fingerprint": "fp-safe"}]

    def greet(self, account, name, job=""):
        self.calls.append(("greet", name, job))

    def request_resume(self, account, name, *, message="", first_contact=False):
        self.calls.append(("request_resume", name, message, first_contact))

    def send_text(self, account, name, message):
        self.calls.append(("send_text", name, message))


class CommunicationWorkerTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig("edge.exe", "profile", 53470)

    def test_greet_refreshes_discovery_and_requires_exact_fingerprint(self):
        runner = FakeRunner()
        outcome = execute_greet({"request_payload": {
            "target": {"name": "林然", "fingerprint": "fp-safe", "job_title": "测试工程师"}
        }}, self.account, runner)
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(runner.calls[-1], ("greet", "林然", "测试工程师"))

    def test_greet_with_missing_identity_waits_for_human(self):
        runner = FakeRunner()
        outcome = execute_greet({"request_payload": {
            "target": {"name": "林然", "fingerprint": "", "job_title": "测试工程师"}
        }}, self.account, runner)
        self.assertEqual(outcome["status"], "waiting_human")
        self.assertNotIn("greet", [call[0] for call in runner.calls])

    def test_greet_with_same_name_candidates_never_clicks_first_match(self):
        runner = FakeRunner()
        runner.recommend = lambda account, job: [
            {"display_name": "林然", "fingerprint": "fp-safe"},
            {"display_name": "林然", "fingerprint": "fp-other"},
        ]
        outcome = execute_greet({"request_payload": {
            "target": {"name": "林然", "fingerprint": "fp-safe", "job_title": "测试工程师"}
        }}, self.account, runner)
        self.assertEqual(outcome["status"], "waiting_human")
        self.assertNotIn("greet", [call[0] for call in runner.calls])

    def test_request_resume_and_interview_use_confirmed_snapshots(self):
        runner = FakeRunner()
        resume = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"},
            "message": "请发送简历",
            "first_contact": True,
        }}, self.account, runner)
        interview = execute_send_interview({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"}, "message": "周五上午十点面试"
        }}, self.account, runner)
        self.assertEqual(resume["status"], "succeeded")
        self.assertEqual(interview["status"], "succeeded")
        self.assertIn(("request_resume", "林然", "请发送简历", True), runner.calls)
        self.assertIn(("send_text", "林然", "周五上午十点面试"), runner.calls)
