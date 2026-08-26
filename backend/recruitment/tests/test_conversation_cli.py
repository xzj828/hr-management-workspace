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

    @patch("recruitment.rpa.playwright_adapter.BrowserInventory")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_stable_first_contact_refreshes_opens_and_rechecks_platform_id(self, run, inventory):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        inventory.return_value.conversation_rows.return_value = [{
            "index": 3,
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "preview": "你好",
            "unread_count": 1,
            "selected": False,
        }]
        inventory.return_value.selected_conversation.return_value = {
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "selected": True,
        }

        self.runner.request_resume_by_external_id(
            self.account,
            "conversation-101",
            message="您好，方便发送一份简历吗？",
            first_contact=True,
            job_title="测试工程师",
        )

        commands = [call.args[0][1:] for call in run.call_args_list]
        self.assertEqual(commands[0], ["list"])
        self.assertEqual(commands[1], ["chat", "林然", "--index", "3", "--strict"])
        self.assertEqual(
            commands[2],
            ["send", "--text", "您好，方便发送一份简历吗？", "--request-resume"],
        )
        self.assertGreaterEqual(inventory.return_value.selected_conversation.call_count, 2)
        inventory.return_value.conversation_rows.assert_called_once_with(
            job_title="测试工程师",
            unread=False,
        )

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_send_text_rejects_line_breaks_before_subprocess(self, run):
        with self.assertRaises(BossCliError):
            self.runner.send_text(self.account, "林然", "第一行\n第二行")
        run.assert_not_called()

