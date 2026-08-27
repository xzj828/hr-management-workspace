from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from recruitment.rpa.cli import BossCliError, BossCliRunner, CliAccountConfig


class ConversationCliTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig("edge.exe", "profile-dir", 53470)
        self.runner = BossCliRunner(cli_path="C:/tools/boss.exe")

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_greet_uses_argument_list_without_shell(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        self.runner.greet(self.account, "林然", job="测试工程师")
        command = run.call_args.args[0]
        self.assertTrue(command[0].lower().endswith("boss.exe"))
        self.assertEqual(command[1:], ["greet", "林然", "--job", "测试工程师"])
        self.assertFalse(run.call_args.kwargs["shell"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_request_resume_opens_strict_chat_before_action(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        self.runner.request_resume(self.account, "林然")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(commands[0][0].lower().endswith("boss.exe"))
        self.assertEqual(commands[0][1:], ["chat", "林然", "--strict"])
        self.assertEqual(commands[1][1:], ["action", "request-attachment-resume"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_first_contact_sends_approved_text_then_requests_resume(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        self.runner.request_resume(
            self.account,
            "林然",
            message="您好，方便发送一份简历吗？",
            first_contact=True,
        )
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(commands[0][0].lower().endswith("boss.exe"))
        self.assertEqual(commands[0][1:], ["chat", "林然", "--strict"])
        self.assertEqual(
            commands[1][1:],
            ["send", "--text", "您好，方便发送一份简历吗？", "--request-resume"],
        )

    @patch.object(BossCliRunner, "_run_chat_bridge")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_stable_first_contact_refreshes_opens_and_rechecks_platform_id(self, run, bridge):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        snapshot = {
            "index": 3,
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "preview": "你好",
            "unread_count": 1,
            "selected": True,
            "messages": [{"direction": "candidate", "content": "你好"}],
        }
        selected = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "selected": True,
        }
        bridge.side_effect = [
            {"ok": True, "conversation": snapshot},
            {"ok": True, "conversation": selected},
            {"ok": True, "receipt": {
                **selected,
                "verified": True,
                "greeting_verified": True,
                "resume_requested": True,
                "request_acknowledged": True,
                "expected_external_id": "conversation-101",
                "observed_external_id": "conversation-101",
            }},
        ]

        self.runner.request_resume_by_external_id(
            self.account,
            "conversation-101",
            message="您好，方便发送一份简历吗？",
            first_contact=True,
            job_title="测试工程师",
        )

        run.assert_not_called()
        operations = [call.args[1] for call in bridge.call_args_list]
        self.assertEqual(operations, ["open", "selected", "request_resume"])
        request_payload = bridge.call_args_list[2].args[2]
        self.assertEqual(request_payload["external_id"], "conversation-101")
        self.assertEqual(request_payload["message"], "您好，方便发送一份简历吗？")
        self.assertEqual(request_payload["previous_count"], 0)
        self.assertIs(request_payload["first_contact"], True)

    @patch.object(BossCliRunner, "_run_chat_bridge")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_stable_request_resume_rejects_receipt_without_native_ack(self, run, bridge):
        selected = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
        }
        bridge.side_effect = [
            {"ok": True, "conversation": {**selected, "messages": []}},
            {"ok": True, "conversation": selected},
            {"ok": True, "receipt": {
                **selected,
                "verified": True,
                "greeting_verified": True,
                "resume_requested": True,
                "observed_external_id": "conversation-101",
            }},
        ]

        with self.assertRaises(BossCliError):
            self.runner.request_resume_by_external_id(
                self.account,
                "conversation-101",
                message="您好，方便发送一份简历吗？",
                first_contact=True,
                job_title="测试工程师",
            )

        run.assert_not_called()

    @patch.object(BossCliRunner, "_run_chat_bridge")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_stable_first_contact_never_requests_resume_without_message_receipt(self, run, bridge):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        snapshot = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "messages": [],
        }
        selected = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
        }
        bridge.side_effect = [
            {"ok": True, "conversation": snapshot},
            {"ok": True, "conversation": selected},
            BossCliError("发送后未确认聊天区出现新的己方消息"),
        ]

        with self.assertRaises(BossCliError):
            self.runner.request_resume_by_external_id(
                self.account,
                "conversation-101",
                message="您好，方便发送一份简历吗？",
                first_contact=True,
                job_title="测试工程师",
            )

        run.assert_not_called()

    @patch.object(BossCliRunner, "_run_chat_bridge")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_stable_send_text_uses_same_edge_session_and_requires_receipt(self, run, bridge):
        snapshot = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "messages": [],
        }
        selected = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
        }
        bridge.side_effect = [
            {"ok": True, "conversation": snapshot},
            {"ok": True, "conversation": selected},
            {"ok": True, "receipt": {**selected, "verified": True}},
        ]

        result = self.runner.send_text_by_external_id(
            self.account,
            "conversation-101",
            "您好，方便发送一份简历吗？",
            job_title="测试工程师",
        )

        run.assert_not_called()
        self.assertTrue(result["sent"])
        self.assertEqual(
            [call.args[1] for call in bridge.call_args_list],
            ["open", "selected", "send_text"],
        )

    @patch.object(BossCliRunner, "_run_chat_bridge")
    def test_job_scoped_conversations_do_not_run_cli_list_first(self, bridge):
        bridge.return_value = {"ok": True, "rows": [{
            "index": 1,
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "preview": "你好",
            "unread_count": 1,
            "selected": False,
        }]}

        output = self.runner.conversations(
            self.account,
            unread=True,
            job_title="测试工程师",
        )

        bridge.assert_called_once_with(
            self.account,
            "list",
            {"job_title": "测试工程师", "unread": True},
        )
        self.assertIn("external_id:conversation-101", output)

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_send_text_rejects_line_breaks_before_subprocess(self, run):
        with self.assertRaises(BossCliError):
            self.runner.send_text(self.account, "林然", "第一行\n第二行")
        run.assert_not_called()

