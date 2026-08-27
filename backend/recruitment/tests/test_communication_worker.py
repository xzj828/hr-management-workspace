from unittest.mock import patch

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

    def conversations(self, account, *, job_title=""):
        self.calls.append(("conversations", job_title))
        return "1. 林然｜产品经理｜external_id:boss-1｜未读 1"

    def send_text(self, account, name, message):
        self.calls.append(("send_text", name, message))


class CommunicationWorkerTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig("edge.exe", "profile", 53470)

    def test_greet_does_not_use_name_based_adapter_even_with_fingerprint(self):
        runner = FakeRunner()
        outcome = execute_greet({"request_payload": {
            "target": {"name": "林然", "fingerprint": "fp-safe", "job_title": "测试工程师"}
        }}, self.account, runner)
        self.assertEqual(outcome["status"], "waiting_human")
        self.assertNotIn("greet", [call[0] for call in runner.calls])

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

    def test_matching_list_id_still_does_not_authorize_name_based_send_actions(self):
        runner = FakeRunner()
        resume = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"},
            "message": "请发送简历",
            "first_contact": True,
        }}, self.account, runner)
        interview = execute_send_interview({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"}, "message": "周五上午十点面试"
        }}, self.account, runner)
        self.assertEqual(resume["status"], "waiting_human")
        self.assertEqual(interview["status"], "waiting_human")
        self.assertEqual(resume["error_code"], "stable_identity_action_unavailable")
        self.assertNotIn("request_resume", [call[0] for call in runner.calls])
        self.assertNotIn("send_text", [call[0] for call in runner.calls])

    def test_request_resume_stops_when_refreshed_conversation_name_is_ambiguous(self):
        runner = FakeRunner()
        runner.conversations = lambda account, **kwargs: "1. 林然｜产品经理\n2. 林然｜测试工程师"

        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"},
            "message": "请发送简历",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "waiting_human")
        self.assertNotIn("request_resume", [call[0] for call in runner.calls])

    def test_request_resume_wrong_external_id_probe_never_calls_action(self):
        runner = FakeRunner()
        runner.conversations = lambda account, **kwargs: "1. 林然｜产品经理｜external_id:boss-other"

        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"},
            "message": "请发送简历",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "waiting_human")
        self.assertNotIn("request_resume", [call[0] for call in runner.calls])

    def test_request_resume_name_only_probe_never_calls_action(self):
        runner = FakeRunner()
        runner.conversations = lambda account, **kwargs: "1. 林然｜产品经理"

        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"},
            "message": "请发送简历",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "waiting_human")
        self.assertNotIn("request_resume", [call[0] for call in runner.calls])

    def test_request_resume_uses_stable_adapter_for_first_contact(self):
        runner = FakeRunner()

        def stable_action(account, external_id, *, message="", first_contact=False, job_title=""):
            runner.calls.append(("request_resume_stable", external_id, message, first_contact, job_title))
            return {
                "verified": True,
                "greeting_verified": first_contact,
                "resume_requested": True,
                "request_acknowledged": True,
                "observed_external_id": external_id,
            }

        runner.request_resume_by_external_id = stable_action

        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1", "job_title": "产品经理"},
            "message": "您好，方便发送一份简历吗？",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "succeeded")
        self.assertIn(
            ("request_resume_stable", "boss-1", "您好，方便发送一份简历吗？", True, "产品经理"),
            runner.calls,
        )

    @patch("recruitment.management.commands.run_rpa_worker.time.sleep")
    def test_request_resume_rechecks_transient_empty_scoped_snapshot_before_action(self, sleep):
        runner = FakeRunner()
        snapshots = iter([
            "",
            "1. 林然｜产品经理｜external_id:boss-1｜未读 1",
        ])
        runner.conversations = lambda account, **kwargs: next(snapshots)

        def stable_action(account, external_id, *, message="", first_contact=False, job_title=""):
            return {
                "verified": True,
                "greeting_verified": first_contact,
                "resume_requested": True,
                "request_acknowledged": True,
                "observed_external_id": external_id,
            }

        runner.request_resume_by_external_id = stable_action
        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1", "job_title": "产品经理"},
            "message": "您好，方便发送一份简历吗？",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "succeeded")
        sleep.assert_called_once_with(0.4)

    def test_request_resume_adapter_exception_is_never_retryable(self):
        runner = FakeRunner()

        def uncertain_action(account, external_id, *, message="", first_contact=False, job_title=""):
            raise RuntimeError("connection lost after click")

        runner.request_resume_by_external_id = uncertain_action

        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1"},
            "message": "您好，方便发送一份简历吗？",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "waiting_human")
        self.assertEqual(outcome["error_code"], "external_result_uncertain")

    def test_request_resume_without_native_acknowledgement_is_waiting_human(self):
        runner = FakeRunner()

        runner.request_resume_by_external_id = lambda *args, **kwargs: {
            "verified": True,
            "greeting_verified": True,
            "resume_requested": True,
            "observed_external_id": "boss-1",
        }

        outcome = execute_request_resume({"request_payload": {
            "target": {"name": "林然", "external_id": "boss-1", "job_title": "产品经理"},
            "message": "您好，方便发送一份简历吗？",
            "first_contact": True,
        }}, self.account, runner)

        self.assertEqual(outcome["status"], "waiting_human")
        self.assertEqual(outcome["error_code"], "external_result_uncertain")
