import subprocess
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from recruitment.rpa.cli import (
    BossCliError,
    BossCliRunner,
    BossCliTimeout,
    CliAccountConfig,
    parse_positions,
)


POSITIONS_OUTPUT = """已读取 2 个职位。
状态统计：开放中 1｜待开放 0｜已关闭 1
来源页面：https://www.zhipin.com/web/chat/job/list
职位明细：
1. 实施工程师｜状态:开放中｜北京｜看过我:2｜沟通过:1｜感兴趣:0｜ID:job-101
2. 运维工程师｜状态:已关闭｜上海｜看过我:4｜沟通过:2｜感兴趣:1｜ID:job-102
"""


class PositionParserTests(SimpleTestCase):
    def test_position_parser_returns_stable_records(self):
        rows = parse_positions(POSITIONS_OUTPUT)

        self.assertEqual(rows[0]["external_id"], "job-101")
        self.assertEqual(rows[0]["title"], "实施工程师")
        self.assertEqual(rows[0]["status"], "open")
        self.assertEqual(rows[1]["status"], "closed")

    def test_missing_id_gets_deterministic_derived_id(self):
        line = "1. 产品经理｜状态:待开放｜杭州"

        first = parse_positions(line)[0]
        second = parse_positions(line)[0]

        self.assertEqual(first["external_id"], second["external_id"])
        self.assertTrue(first["external_id"].startswith("derived-"))
        self.assertEqual(first["status"], "paused")


class BossCliRunnerTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig(
            executable="C:/Program Files/Google/Chrome/Application/chrome.exe",
            user_data_dir="C:/hr/profiles/boss-a",
            cdp_port=53470,
        )

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_account_environment_is_explicit(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, POSITIONS_OUTPUT.encode("utf-8"), b"")
        runner = BossCliRunner(cli_path="C:/tools/boss.cmd")

        rows = runner.positions(self.account)

        env = run.call_args.kwargs["env"]
        self.assertEqual(env["CHROME_PATH"], self.account.executable)
        self.assertEqual(env["BOSS_BROWSER_USER_DATA_DIR"], self.account.user_data_dir)
        self.assertEqual(env["BOSS_BROWSER_REMOTE_DEBUGGING_PORT"], "53470")
        self.assertEqual(env["BOSS_BROWSER_HEADLESS"], "false")
        self.assertEqual(rows[0]["external_id"], "job-101")
        self.assertFalse(run.call_args.kwargs["shell"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_gb18030_output_falls_back_cleanly(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "0.6.6 中文".encode("gb18030"), b"")

        result = BossCliRunner(cli_path="C:/tools/boss.cmd").version()

        self.assertEqual(result, "0.6.6 中文")

    @patch("recruitment.rpa.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("boss", 1))
    def test_timeout_is_normalized(self, run):
        with self.assertRaises(BossCliTimeout):
            BossCliRunner(cli_path="C:/tools/boss.cmd").positions(self.account)

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_nonzero_exit_is_normalized(self, run):
        run.return_value = subprocess.CompletedProcess([], 2, b"", "执行失败".encode("gb18030"))

        with self.assertRaisesMessage(BossCliError, "执行失败"):
            BossCliRunner(cli_path="C:/tools/boss.cmd").positions(self.account)

    def test_environment_override_has_discovery_priority(self):
        with patch.dict("os.environ", {"BOSS_CLI": "C:/custom/boss.cmd"}), patch.object(Path, "exists", return_value=True):
            runner = BossCliRunner()

        self.assertEqual(runner.cli_path, "C:/custom/boss.cmd")

