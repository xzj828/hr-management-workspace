import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from recruitment.rpa.cli import (
    BossCliCancelled,
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
        runner = BossCliRunner(cli_path="C:/tools/boss.exe")

        with patch.dict(os.environ, {
            "RPA_WORKER_TOKEN": "must-not-leak",
            "DJANGO_SECRET_KEY": "must-not-leak",
            "NODE_OPTIONS": "--require=C:/untrusted.js",
        }):
            rows = runner.positions(self.account)

        env = run.call_args.kwargs["env"]
        self.assertEqual(env["CHROME_PATH"], self.account.executable)
        self.assertEqual(env["BOSS_BROWSER_USER_DATA_DIR"], self.account.user_data_dir)
        self.assertEqual(env["BOSS_BROWSER_REMOTE_DEBUGGING_PORT"], "53470")
        self.assertEqual(env["BOSS_BROWSER_HEADLESS"], "false")
        self.assertNotIn("RPA_WORKER_TOKEN", env)
        self.assertNotIn("DJANGO_SECRET_KEY", env)
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertNotIn("PATH", env)
        self.assertEqual(rows[0]["external_id"], "job-101")
        self.assertFalse(run.call_args.kwargs["shell"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_chat_bridge_uses_bundled_puppeteer_fixed_argv_and_json_stdin(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps({"ok": True, "rows": []}).encode("utf-8"), b""
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            node = root / "node.exe"
            entry = root / "boss-cli" / "dist" / "cli" / "index.js"
            entry.parent.mkdir(parents=True)
            entry.touch()
            node.touch()
            (root / "boss-cli" / "package.json").write_text(
                json.dumps({"name": "@joohw/boss-cli", "version": "0.6.6"}),
                encoding="utf-8",
            )
            runner = BossCliRunner(cli_path=[str(node), str(entry)])

            with patch.dict(os.environ, {"RPA_WORKER_TOKEN": "must-not-leak"}):
                result = runner._run_chat_bridge(
                    self.account,
                    "list",
                    {"job_title": "测试工程师", "unread": True},
                )

        command = run.call_args.args[0]
        request = json.loads(run.call_args.kwargs["input"].decode("utf-8"))
        self.assertTrue(command[1].endswith("boss_chat_bridge.mjs"))
        self.assertTrue(command[2].endswith("boss-cli"))
        self.assertEqual(request["port"], 53470)
        self.assertEqual(request["job_title"], "测试工程师")
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotIn("RPA_WORKER_TOKEN", run.call_args.kwargs["env"])
        self.assertTrue(result["ok"])

    @patch("recruitment.rpa.cli.subprocess.Popen")
    def test_login_launcher_uses_fixed_argv_minimal_env_and_no_pipes(self, popen):
        runner = BossCliRunner(cli_path=["C:/Program Files/nodejs/node.exe", "C:/safe/boss-cli.js"])

        runner.start_login(self.account)

        command = popen.call_args.args[0]
        self.assertEqual(command[-1], "login")
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("PATH", popen.call_args.kwargs["env"])

    def test_login_cleanup_kills_after_graceful_timeout(self):
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("boss", 2), None]

        BossCliRunner.stop_login(process)

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_login_cleanup_is_best_effort(self):
        process = MagicMock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError("already gone")

        BossCliRunner.stop_login(process)

        process.terminate.assert_called_once()

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_gb18030_output_falls_back_cleanly(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "0.6.6 中文".encode("gb18030"), b"")

        result = BossCliRunner(cli_path="C:/tools/boss.exe").version()

        self.assertEqual(result, "0.6.6 中文")

    @patch("recruitment.rpa.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("boss", 1))
    def test_timeout_is_normalized(self, run):
        with self.assertRaises(BossCliTimeout):
            BossCliRunner(cli_path="C:/tools/boss.exe").positions(self.account)

    @patch("recruitment.rpa.cli.subprocess.Popen")
    def test_monitored_command_stops_cli_process_when_cancelled(self, popen):
        process = popen.return_value
        process.poll.return_value = None
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("boss", 0.25),
            (b"", b""),
        ]
        runner = BossCliRunner(
            cli_path="C:/tools/boss.exe",
            cancel_requested=lambda: True,
        )

        with self.assertRaises(BossCliCancelled):
            runner.positions(self.account)

        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_nonzero_exit_is_normalized(self, run):
        run.return_value = subprocess.CompletedProcess([], 2, b"", "执行失败".encode("gb18030"))

        with self.assertRaisesMessage(BossCliError, "执行失败"):
            BossCliRunner(cli_path="C:/tools/boss.exe").positions(self.account)

    def test_environment_override_points_node_at_safe_javascript_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            node = root / "node.exe"
            entry = root / "boss-cli.js"
            node.touch()
            entry.touch()
            with patch.dict(os.environ, {"BOSS_CLI": str(entry), "BOSS_NODE": str(node)}):
                runner = BossCliRunner()

        self.assertEqual(Path(runner.cli_path), node.resolve())
        self.assertEqual(runner.invocation.prefix, (str(entry.resolve()),))

    def test_windows_script_shims_are_always_rejected(self):
        for suffix in (".cmd", ".bat", ".ps1"):
            with self.subTest(suffix=suffix):
                with self.assertRaisesMessage(BossCliError, "禁止执行"):
                    BossCliRunner(cli_path=f"C:/tools/boss{suffix}")

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_business_shell_characters_remain_literal_node_arguments(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        runner = BossCliRunner(cli_path="C:/tools/boss.exe")

        runner.search(self.account, "Vue & AI")

        self.assertEqual(run.call_args.args[0][-2:], ["search", "Vue & AI"])
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_real_node_entry_does_not_execute_fake_npm_or_boss_shims(self):
        node = shutil.which("node.exe") or shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for the Windows CLI integration fixture")

        with tempfile.TemporaryDirectory(prefix="boss cli & fixture ") as directory:
            root = Path(directory)
            entry = root / "entry.js"
            marker = root / "shim-executed.txt"
            entry.write_text(
                "console.log(JSON.stringify({argv: process.argv.slice(2), "
                "workerToken: process.env.RPA_WORKER_TOKEN || null, "
                "path: process.env.PATH || null}));",
                encoding="utf-8",
            )
            for shim_name in ("npm.cmd", "boss.cmd"):
                (root / shim_name).write_text(
                    f'@echo executed>{marker}\r\n', encoding="utf-8"
                )

            with patch.dict(os.environ, {
                "BOSS_CLI": str(entry),
                "BOSS_NODE": node,
                "PATH": f"{root}{os.pathsep}{os.environ.get('PATH', '')}",
                "RPA_WORKER_TOKEN": "must-not-reach-node",
            }):
                runner = BossCliRunner()
                result = runner._run(
                    ["search", "Vue 3"], env=runner._base_env(), timeout_seconds=20
                )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["argv"], ["search", "Vue 3"])
            self.assertIsNone(payload["workerToken"])
            self.assertIsNone(payload["path"])
            self.assertFalse(marker.exists())

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_node_and_javascript_entry_are_passed_as_fixed_argv(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b"0.6.6", b"")
        runner = BossCliRunner(cli_path=["C:/Program Files/nodejs/node.exe", "C:/safe & fixed/index.js"])

        runner.version()

        command = run.call_args.args[0]
        self.assertEqual(Path(command[0]), Path("C:/Program Files/nodejs/node.exe").resolve())
        self.assertEqual(Path(command[1]), Path("C:/safe & fixed/index.js").resolve())
        self.assertEqual(command[2:], ["--version"])
        self.assertFalse(run.call_args.kwargs["shell"])
