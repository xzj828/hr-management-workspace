from io import StringIO
from contextlib import nullcontext
import threading
import time
from unittest.mock import patch
from types import SimpleNamespace

from django.test import SimpleTestCase

from recruitment.management.commands.run_rpa_worker import (
    AccountStatusObserver,
    Command,
    OPEN_LOGIN_MAX_POLLS,
    WorkerEngine,
    WorkerHeartbeat,
    execute_check_status,
    execute_sync_positions,
    execute_sync_conversations,
    run_worker_loop,
)
from recruitment.rpa.cli import BossCliCancelled, BossCliError, CliAccountConfig
from recruitment.rpa.status import BossBrowserStatus, classify_boss_pages
from recruitment.rpa.status import inspect_boss_status


class BossStatusTests(SimpleTestCase):
    def test_login_page_requires_manual_login(self):
        status = classify_boss_pages([{"url": "https://www.zhipin.com/web/user/?ka=header-login", "title": "登录BOSS直聘"}])

        self.assertEqual(status.login_status, "waiting_login")
        self.assertTrue(status.target_page_ready)

    def test_invalid_qr_token_requires_human(self):
        status = classify_boss_pages([{"url": "https://www.zhipin.com/web/user/", "title": "Token 无效"}])

        self.assertEqual(status.login_status, "waiting_human")
        self.assertEqual(status.verification_status, "token_invalid")

    def test_security_page_is_never_bypassed(self):
        status = classify_boss_pages([{"url": "https://www.zhipin.com/web/common/security-check", "title": "安全验证"}])

        self.assertEqual(status.login_status, "waiting_human")
        self.assertEqual(status.verification_status, "risk_control")

    def test_authenticated_recruiter_chat_page_is_ready(self):
        status = classify_boss_pages([
            {"url": "https://www.zhipin.com/web/chat/index", "title": "沟通"},
        ])

        self.assertEqual(status.login_status, "ready")

    def test_public_homepage_is_not_treated_as_authenticated(self):
        status = classify_boss_pages([
            {"url": "https://www.zhipin.com/", "title": "BOSS直聘"},
        ])

        self.assertEqual(status.login_status, "waiting_login")
        self.assertFalse(status.target_page_ready)

    def test_unrelated_page_cannot_smuggle_host_in_query(self):
        status = classify_boss_pages([
            {"url": "https://example.com/?next=https://www.zhipin.com/web/chat/index", "title": "unknown"},
        ])

        self.assertEqual(status.login_status, "waiting_login")

    def test_error_page_fails_closed(self):
        status = classify_boss_pages([
            {"url": "https://www.zhipin.com/web/common/error", "title": "页面出错"},
        ])

        self.assertEqual(status.login_status, "error")

    @patch("recruitment.rpa.status.managed_cdp_matches", return_value=False)
    @patch("recruitment.rpa.status.cdp_is_running", return_value=True)
    def test_wrong_managed_profile_fails_closed_before_page_classification(self, running, matches):
        status = inspect_boss_status(53470, user_data_dir="C:/profiles/expected")

        self.assertEqual(status.login_status, "error")
        self.assertEqual(status.verification_status, "cdp_identity_mismatch")


class WorkerEngineTests(SimpleTestCase):
    def test_conversation_stop_before_list_never_calls_platform(self):
        class Runner:
            calls = 0

            def conversations(self, account):
                self.calls += 1
                return ""

        runner = Runner()
        outcome = execute_sync_conversations(
            {},
            CliAccountConfig("edge.exe", "profile", 53470),
            runner,
            checkpoint=lambda phase, sequence: False,
        )

        self.assertEqual(runner.calls, 0)
        self.assertTrue(outcome["result"]["checkpoint_stopped"])
        self.assertEqual(outcome["result"]["conversations"], [])

    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=True)
    def test_cancelled_cli_reports_cancelled_without_closing_browser(self, matches, inspect):
        inspect.return_value = BossBrowserStatus("ready", detail="已登录")
        completed = []

        class Api:
            def event(self, task_id, payload):
                return payload

            def control(self, task_id, *, lease_token, lease_generation):
                return {"cancel_requested": True}

            def complete(self, task_id, payload):
                completed.append(payload)

        class Runner:
            cancel_requested = None

            def set_cancel_check(self, callback):
                self.cancel_requested = callback

        runner = Runner()
        engine = WorkerEngine(api=Api(), runner=runner, worker_key="local-worker")
        task = {
            "id": "task-cancelled",
            "action": "sync_positions",
            "lease_token": "test-lease-token",
            "lease_generation": 1,
            "browser": {
                "executable": "edge.exe",
                "user_data_dir": "C:/profiles/expected",
                "cdp_port": 53470,
            },
        }

        with patch(
            "recruitment.management.commands.run_rpa_worker.ProfileLock",
            side_effect=lambda path: nullcontext(),
        ), patch.object(engine, "_execute", side_effect=BossCliCancelled("任务已取消")):
            outcome = engine.execute_task(task)

        self.assertEqual(outcome["status"], "cancelled")
        self.assertEqual(completed[0]["status"], "cancelled")
        self.assertTrue(runner.cancel_requested())

    @patch("recruitment.management.commands.run_rpa_worker.BrowserInventory")
    def test_position_sync_falls_back_to_browser_when_cli_navigation_fails(self, inventory):
        expected = [{"external_id": "derived-1", "title": "前置部署工程师", "status": "open", "raw": "前置部署工程师"}]
        inventory.return_value.positions.return_value = expected

        class Runner:
            def positions(self, account):
                raise BossCliError("无法进入职位管理")

        account = CliAccountConfig("edge.exe", "C:/profiles/a", 53470)
        outcome = execute_sync_positions({}, account, Runner())

        self.assertEqual(outcome["result"]["positions"], expected)
        inventory.assert_called_once_with(53470)

    @patch("recruitment.management.commands.run_rpa_worker.BrowserInventory")
    def test_conversation_sync_returns_every_chat_message(self, inventory):
        inventory.return_value.download_resume_attachments.return_value = []

        class Runner:
            def conversations(self, account, unread=False):
                return "1. 林然｜产品经理｜未读 2"

            def open_chat(self, account, name):
                return SimpleNamespace(stdout="""成功进入候选人聊天：林然
完整聊天消息：
[candidate] 2026-08-25 09:00 你好
[you] 2026-08-25 09:01 您好
[candidate] 2026-08-25 09:02 这是我的简历
""")

        outcome = execute_sync_conversations(
            {"request_payload": {"job": 7, "job_title": "产品经理"}},
            CliAccountConfig("edge.exe", "profile", 53470),
            Runner(),
        )

        messages = outcome["result"]["conversations"][0]["messages"]
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[-1]["content"], "这是我的简历")

    @patch("recruitment.management.commands.run_rpa_worker.BrowserInventory")
    def test_sync_opens_only_unread_conversations_for_selected_job(self, inventory):
        inventory.return_value.download_resume_attachments.return_value = []

        class Runner:
            def __init__(self):
                self.called_unread = None
                self.opened = []

            def conversations(self, account, unread=False):
                self.called_unread = unread
                return (
                    "1. 林然｜产品经理｜已读\n"
                    "2. 周青｜测试工程师｜未读 1\n"
                    "3. 陈思｜产品经理｜未读 2\n"
                )

            def open_chat(self, account, name):
                self.opened.append(name)
                return SimpleNamespace(stdout="完整聊天消息：\n[candidate] 2026-08-25 09:00 你好")

        runner = Runner()
        outcome = execute_sync_conversations(
            {"request_payload": {"job": 7, "job_title": "产品经理"}},
            CliAccountConfig("edge.exe", "profile", 53470),
            runner,
        )

        self.assertTrue(runner.called_unread)
        self.assertEqual(runner.opened, ["陈思"])
        conversations = outcome["result"]["conversations"]
        by_name = {row["name"]: row for row in conversations}
        self.assertIn("messages", by_name["陈思"])
        self.assertEqual(by_name["林然"]["sync_error"], "会话已读，未打开")
        self.assertEqual(by_name["周青"]["sync_error"], "会话岗位与当前选择岗位不一致，未打开")

    @patch("recruitment.management.commands.run_rpa_worker.BrowserInventory")
    def test_bootstrap_backfill_opens_read_conversations_only_for_selected_job(self, inventory):
        inventory.return_value.download_resume_attachments.return_value = []

        class Runner:
            def __init__(self):
                self.called_unread = None
                self.opened = []

            def conversations(self, account, unread=False):
                self.called_unread = unread
                return "1. 林然｜产品经理｜selected:1｜已读\n2. 周青｜测试工程师｜已读"

            def open_chat(self, account, name):
                self.opened.append(name)
                return SimpleNamespace(stdout="完整聊天消息：\n[candidate] 2026-08-25 09:00 你好")

        runner = Runner()
        outcome = execute_sync_conversations(
            {"request_payload": {
                "job": 7,
                "job_title": "产品经理",
                "backfill_conversations": True,
            }},
            CliAccountConfig("edge.exe", "profile", 53470),
            runner,
        )

        self.assertFalse(runner.called_unread)
        self.assertEqual(runner.opened, ["林然"])
        self.assertEqual(outcome["result"]["conversations"][0]["messages"][0]["content"], "你好")

    @patch("recruitment.management.commands.run_rpa_worker.BrowserInventory")
    def test_stable_conversation_sync_never_falls_back_to_name_open(self, inventory):
        inventory.return_value.download_resume_attachments.return_value = []

        class Runner:
            def __init__(self):
                self.stable_ids = []

            def conversations(self, account, unread=False):
                return "1. 同名候选人｜产品经理｜external_id:conversation-safe｜未读 1"

            def open_chat_by_external_id(self, account, external_id):
                self.stable_ids.append(external_id)
                return SimpleNamespace(stdout="完整聊天消息：\n[candidate] 2026-08-26 09:00 你好")

            def open_chat(self, account, name):
                raise AssertionError("稳定身份存在时不得按姓名打开")

        runner = Runner()
        outcome = execute_sync_conversations(
            {"request_payload": {"job": 7, "job_title": "产品经理"}},
            CliAccountConfig("edge.exe", "profile", 53470),
            runner,
        )

        self.assertEqual(runner.stable_ids, ["conversation-safe"])
        self.assertEqual(outcome["result"]["conversations"][0]["messages"][0]["content"], "你好")

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
                    {"id": 1, "browser": {"cdp_port": 53470, "user_data_dir": "profile-1"}},
                    {"id": 2, "browser": {"cdp_port": 53471, "user_data_dir": "profile-2"}},
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

    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=False)
    @patch("recruitment.management.commands.run_rpa_worker.cdp_is_running", return_value=True)
    def test_open_login_rejects_cdp_owned_by_another_profile(self, running, matches):
        runner = type("Runner", (), {"login": lambda self, account: (_ for _ in ()).throw(AssertionError("must not launch"))})()

        outcome = execute_check_status(
            {"open_login": True},
            CliAccountConfig("edge.exe", "C:/profiles/expected", 53470),
            runner,
        )

        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "cdp_identity_mismatch")

    def test_unknown_action_is_not_executed(self):
        api = type("Api", (), {"complete": lambda self, task_id, payload: payload})()
        engine = WorkerEngine(api=api, runner=object(), worker_key="local-worker")

        with patch.object(engine, "_execute") as execute:
            outcome = engine.execute_task({"id": "task-1", "action": "send_message", "browser": {}})

        execute.assert_not_called()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "unsupported_action")

    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=False)
    def test_formal_task_rechecks_managed_cdp_before_executor(self, matches):
        completed = []
        api = type("Api", (), {
            "event": lambda self, task_id, payload: payload,
            "complete": lambda self, task_id, payload: completed.append(payload),
        })()
        engine = WorkerEngine(api=api, runner=object(), worker_key="local-worker")
        task = {
            "id": "task-identity-check",
            "action": "sync_positions",
            "lease_token": "test-lease-token",
            "lease_generation": 1,
            "browser": {
                "executable": "edge.exe",
                "user_data_dir": "C:/profiles/expected",
                "cdp_port": 53470,
            },
        }

        with patch(
            "recruitment.management.commands.run_rpa_worker.ProfileLock",
            side_effect=lambda path: nullcontext(),
        ), patch.object(engine, "_execute") as execute:
            outcome = engine.execute_task(task)

        execute.assert_not_called()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "cdp_identity_mismatch")
        self.assertEqual(completed[0]["error_code"], "cdp_identity_mismatch")

    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=True)
    def test_formal_task_rechecks_current_login_before_executor(self, matches, inspect):
        inspect.return_value = BossBrowserStatus("waiting_login", detail="等待人工登录")
        completed = []
        api = type("Api", (), {
            "event": lambda self, task_id, payload: payload,
            "complete": lambda self, task_id, payload: completed.append(payload),
        })()
        engine = WorkerEngine(api=api, runner=object(), worker_key="local-worker")
        task = {
            "id": "task-current-login-check",
            "action": "sync_positions",
            "lease_token": "test-lease-token",
            "lease_generation": 1,
            "browser": {
                "executable": "edge.exe",
                "user_data_dir": "C:/profiles/expected",
                "cdp_port": 53470,
            },
        }

        with patch(
            "recruitment.management.commands.run_rpa_worker.ProfileLock",
            side_effect=lambda path: nullcontext(),
        ), patch.object(engine, "_execute") as execute:
            outcome = engine.execute_task(task)

        execute.assert_not_called()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "boss_account_not_ready")
        self.assertEqual(outcome["result"]["login_status"], "waiting_login")
        self.assertEqual(completed[0]["error_code"], "boss_account_not_ready")

    @patch("recruitment.management.commands.run_rpa_worker.time.sleep")
    @patch("recruitment.management.commands.run_rpa_worker.record_managed_cdp")
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_waits_for_browser_debugging(self, inspect, record, sleep):
        inspect.side_effect = [
            BossBrowserStatus("browser_stopped", detail="starting"),
            BossBrowserStatus("waiting_login", detail="ready", target_page_ready=True),
        ]
        runner = type("Runner", (), {"login": lambda self, account: None})()
        account = CliAccountConfig("edge.exe", "C:/profiles/a", 53470)

        with patch(
            "recruitment.management.commands.run_rpa_worker.cdp_is_running",
            return_value=False,
        ):
            outcome = execute_check_status({"open_login": True}, account, runner)

        self.assertEqual(inspect.call_count, 2)
        record.assert_called_once_with(53470, "C:/profiles/a")
        sleep.assert_called_once()
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(outcome["result"]["login_status"], "waiting_login")

    @patch("recruitment.management.commands.run_rpa_worker.record_managed_cdp")
    @patch("recruitment.management.commands.run_rpa_worker.cdp_is_running", side_effect=[False, True])
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_releases_cli_after_cdp_is_ready(self, inspect, running, record):
        inspect.return_value = BossBrowserStatus(
            "waiting_login", detail="等待人工登录", target_page_ready=True,
        )
        process = SimpleNamespace(poll=lambda: None)

        class Runner:
            started = None
            stopped = None

            def start_login(self, account):
                self.started = account
                return process

            def stop_login(self, value):
                self.stopped = value

        runner = Runner()
        account = CliAccountConfig("edge.exe", "C:/profiles/a", 53470)

        outcome = execute_check_status({"open_login": True}, account, runner)

        self.assertIs(runner.started, account)
        self.assertIs(runner.stopped, process)
        record.assert_called_once_with(53470, "C:/profiles/a")
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(outcome["result"]["login_status"], "waiting_login")

    @patch("recruitment.management.commands.run_rpa_worker.record_managed_cdp")
    @patch("recruitment.management.commands.run_rpa_worker.cdp_is_running", side_effect=[False, False])
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_records_identity_when_browser_becomes_ready_between_probes(self, inspect, running, record):
        inspect.return_value = BossBrowserStatus(
            "waiting_login", detail="等待人工登录", target_page_ready=True,
        )
        runner = type("Runner", (), {"login": lambda self, account: None})()
        account = CliAccountConfig("edge.exe", "C:/profiles/a", 53470)

        outcome = execute_check_status({"open_login": True}, account, runner)

        record.assert_called_once_with(53470, "C:/profiles/a")
        self.assertEqual(outcome["status"], "succeeded")

    @patch("recruitment.management.commands.run_rpa_worker.time.sleep")
    @patch("recruitment.management.commands.run_rpa_worker.record_managed_cdp")
    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=True)
    @patch("recruitment.management.commands.run_rpa_worker.cdp_is_running", return_value=True)
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_waits_for_target_page_after_cdp_is_ready(
        self, inspect, running, matches, record, sleep,
    ):
        inspect.side_effect = [
            BossBrowserStatus("waiting_login", detail="未检测到已登录的 BOSS 页面"),
            BossBrowserStatus("waiting_login", detail="等待人工登录", target_page_ready=True),
        ]
        process = SimpleNamespace(poll=lambda: None)

        class Runner:
            def start_login(self, account):
                return process

            def stop_login(self, value):
                self.stopped = value

        runner = Runner()
        outcome = execute_check_status(
            {"open_login": True},
            CliAccountConfig("edge.exe", "C:/profiles/a", 53470),
            runner,
        )

        self.assertEqual(inspect.call_count, 2)
        sleep.assert_called_once()
        self.assertIs(runner.stopped, process)
        self.assertEqual(outcome["status"], "succeeded")

    @patch("recruitment.management.commands.run_rpa_worker.record_managed_cdp")
    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=True)
    @patch("recruitment.management.commands.run_rpa_worker.cdp_is_running", return_value=True)
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_fails_when_cli_exits_before_target_page_opens(
        self, inspect, running, matches, record,
    ):
        inspect.return_value = BossBrowserStatus(
            "waiting_login", detail="未检测到已登录的 BOSS 页面",
        )
        process = SimpleNamespace(poll=lambda: 0)

        class Runner:
            def start_login(self, account):
                return process

            def stop_login(self, value):
                self.stopped = value

        runner = Runner()
        outcome = execute_check_status(
            {"open_login": True},
            CliAccountConfig("edge.exe", "C:/profiles/a", 53470),
            runner,
        )

        self.assertIs(runner.stopped, process)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "boss_login_page_not_opened")

    @patch("recruitment.management.commands.run_rpa_worker.time.sleep")
    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_open_login_browser_failure_is_task_failure(self, inspect, sleep):
        inspect.return_value = BossBrowserStatus("browser_stopped", detail="未启动")
        runner = type("Runner", (), {"login": lambda self, account: None})()

        with patch(
            "recruitment.management.commands.run_rpa_worker.cdp_is_running",
            return_value=False,
        ):
            outcome = execute_check_status(
                {"open_login": True},
                CliAccountConfig("edge.exe", "C:/profiles/a", 53470),
                runner,
            )

        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "browser_login_unavailable")
        self.assertEqual(inspect.call_count, OPEN_LOGIN_MAX_POLLS)

    @patch("recruitment.management.commands.run_rpa_worker.inspect_boss_status")
    def test_risk_control_is_the_only_human_task_state(self, inspect):
        inspect.return_value = BossBrowserStatus(
            "waiting_human", verification_status="risk_control", detail="安全验证",
        )

        outcome = execute_check_status(
            {}, CliAccountConfig("edge.exe", "C:/profiles/a", 53470), object(),
        )

        self.assertEqual(outcome["status"], "waiting_human")


class WorkerCommandReliabilityTests(SimpleTestCase):
    @patch("recruitment.management.commands.run_rpa_worker.AccountStatusObserver")
    @patch("recruitment.management.commands.run_rpa_worker.WorkerApiClient")
    @patch("recruitment.management.commands.run_rpa_worker.probe_boss_cli")
    def test_cli_unavailable_still_heartbeats_without_leasing(self, probe, client_class, observer_class):
        probe.return_value = (
            None,
            "",
            {"code": "boss_cli_unavailable", "message": "未安装"},
        )

        Command().handle(once=True)

        api = client_class.return_value
        heartbeat = api.heartbeat.call_args.args[0]
        self.assertFalse(heartbeat["capabilities"]["boss_cli"])
        self.assertEqual(heartbeat["capabilities"]["boss_cli_error"]["code"], "boss_cli_unavailable")
        api.lease.assert_not_called()
        observer_class.return_value.run_once.assert_called_once_with()

    def test_runtime_api_errors_back_off_and_continue(self):
        class Engine:
            calls = 0

            def run_once(self):
                self.calls += 1
                if self.calls <= 2:
                    raise RuntimeError("temporary")

        class Stop:
            waits = []

            def is_set(self):
                return len(self.waits) >= 3

            def wait(self, seconds):
                self.waits.append(seconds)

        engine = Engine()
        stop = Stop()
        stderr = StringIO()

        run_worker_loop(
            engine=engine,
            stop=stop,
            poll_seconds=3,
            stderr=stderr,
        )

        self.assertEqual(engine.calls, 3)
        self.assertEqual(stop.waits[:3], [1, 2, 3])
        self.assertIn("Worker API 暂时不可用", stderr.getvalue())

    def test_heartbeat_continues_while_engine_is_blocked(self):
        stop = threading.Event()

        class Api:
            calls = 0

            def heartbeat(self, payload):
                self.calls += 1

        class Engine:
            def run_once(self):
                time.sleep(0.08)
                stop.set()

        api = Api()
        heartbeat = WorkerHeartbeat(api, {"hostname": "test"}, interval=0.01)
        thread = threading.Thread(target=heartbeat.run, args=(stop,), daemon=True)
        thread.start()
        run_worker_loop(engine=Engine(), stop=stop, poll_seconds=0.01, stderr=StringIO())
        thread.join(timeout=1)

        self.assertGreaterEqual(api.calls, 3)
