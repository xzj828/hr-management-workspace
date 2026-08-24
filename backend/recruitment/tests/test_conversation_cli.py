from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from recruitment.rpa.cli import BossCliError, BossCliRunner, CliAccountConfig


class ConversationCliTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig("edge.exe", "profile-dir", 53470)
        self.runner = BossCliRunner(cli_path="boss.cmd")

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_greet_uses_argument_list_without_shell(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        self.runner.greet(self.account, "林然", job="测试工程师")
        command = run.call_args.args[0]
        self.assertEqual(command, ["boss.cmd", "greet", "林然", "--job", "测试工程师"])
        self.assertFalse(run.call_args.kwargs["shell"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_request_resume_opens_strict_chat_before_action(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
        self.runner.request_resume(self.account, "林然")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["boss.cmd", "chat", "林然", "--strict"])
        self.assertEqual(commands[1], ["boss.cmd", "action", "resume"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_send_text_rejects_line_breaks_before_subprocess(self, run):
        with self.assertRaises(BossCliError):
            self.runner.send_text(self.account, "林然", "第一行\n第二行")
        run.assert_not_called()

