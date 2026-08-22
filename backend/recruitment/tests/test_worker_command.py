from unittest.mock import patch

from django.test import SimpleTestCase

from recruitment.management.commands.run_rpa_worker import WorkerEngine
from recruitment.rpa.status import classify_boss_pages


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
    def test_unknown_action_is_not_executed(self):
        api = type("Api", (), {"complete": lambda self, task_id, payload: payload})()
        engine = WorkerEngine(api=api, runner=object(), worker_key="local-worker")

        with patch.object(engine, "_execute") as execute:
            outcome = engine.execute_task({"id": "task-1", "action": "send_message", "browser": {}})

        execute.assert_not_called()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "unsupported_action")

