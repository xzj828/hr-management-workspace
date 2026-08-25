from unittest.mock import patch
from types import SimpleNamespace

from django.test import SimpleTestCase

from recruitment.management.commands.run_rpa_worker import (
    AccountStatusObserver,
    WorkerEngine,
    execute_check_status,
    execute_sync_conversations,
)
from recruitment.rpa.cli import CliAccountConfig
from recruitment.rpa.status import BossBrowserStatus, classify_boss_pages


class BossStatusTests(SimpleTestCase):
    def test_login_page_requires_manual_login(self):
        status = classify_boss_pages([{"url": "https://www.zhipin.com/web/user/?ka=header-login", "title": "登录BOSS直聘"}])

        self.assertEqual(status.login_status, "waiting_login")

    def test_invalid_qr_token_requires_human(self):
        status = classify_boss_pages([{"url": "https://www.zhipin.com/web/user/", "title": "Token 无效"}])

        self.assertEqual(status.login_status, "waiting_human")
        self.assertEqual(status.verification_status, "token_invalid")

    def test_security_page_is_never_bypassed(self):
        status = classify_boss_pages([{"url": "https://www.zhipin.com/web/common/security-check", "title": "安全验证"}])

        self.assertEqual(status.login_status, "waiting_human")
        self.assertEqual(status.verification_status, "risk_control")


class WorkerEngineTests(SimpleTestCase):
    @patch("recruitment.management.commands.run_rpa_worker.BrowserInventory")
    def test_conversation_sync_returns_every_chat_message(self, inventory):
        inventory.return_value.download_resume_attachments.return_value = []

        class Runner:
            def conversations(self, account):
                return "1. 林然｜产品经理｜未读 2"

            def open_chat(self, account, name):
                return SimpleNamespace(stdout="""成功进入候选人聊天：林然
完整聊天消息：
[candidate] 2026-08-25 09:00 你好
[you] 2026-08-25 09:01 您好
[candidate] 2026-08-25 09:02 这是我的简历
""")

        outcome = execute_sync_conversations({}, CliAccountConfig("edge.exe", "profile", 53470), Runner())

        messages = outcome["result"]["conversations"][0]["messages"]
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[-1]["content"], "这是我的简历")

    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_status_observer_checks_all_accounts_outside_task_queue(self, inspect):
        inspect.side_effect = [
            BossBrowserStatus("ready", detail="已登录"),
            BossBrowserStatus("browser_stopped", detail="未启动"),
        ]

        class FakeApi:
            submitted = None

            def status_targets(self):
                return {"accounts": [
                    {"id": 1, "browser": {"cdp_port": 53470}},
                    {"id": 2, "browser": {"cdp_port": 53471}},
                ]}

            def submit_status_observations(self, observations):
                self.submitted = observations
                return {"updated": len(observations)}

        api = FakeApi()

        AccountStatusObserver(api, interval=30).run_once()

        self.assertEqual(inspect.call_count, 2)
        self.assertEqual([item["account_id"] for item in api.submitted], [1, 2])
        self.assertEqual(api.submitted[0]["login_status"], "ready")
        self.assertEqual(api.submitted[1]["login_status"], "browser_stopped")

    def test_unknown_action_is_not_executed(self):
        api = type("Api", (), {"complete": lambda self, task_id, payload: payload})()
        engine = WorkerEngine(api=api, runner=object(), worker_key="local-worker")

        with patch.object(engine, "_execute") as execute:
            outcome = engine.execute_task({"id": "task-1", "action": "send_message", "browser": {}})

        execute.assert_not_called()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "unsupported_action")

    @patch("recruitment.management.commands.run_rpa_worker.time.sleep")
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_waits_for_browser_debugging(self, inspect, sleep):
        inspect.side_effect = [
            BossBrowserStatus("browser_stopped", detail="starting"),
            BossBrowserStatus("waiting_login", detail="ready"),
        ]
        runner = type("Runner", (), {"login": lambda self, account: None})()
        account = CliAccountConfig("edge.exe", "C:/profiles/a", 53470)

        outcome = execute_check_status({"open_login": True}, account, runner)

        self.assertEqual(inspect.call_count, 2)
        sleep.assert_called_once()
        self.assertEqual(outcome["result"]["login_status"], "waiting_login")
