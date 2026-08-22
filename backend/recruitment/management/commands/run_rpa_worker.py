import json
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand

from recruitment.rpa.browser import ProfileLock, ProfileLockedError
from recruitment.rpa.cli import BossCliError, BossCliRunner, CliAccountConfig
from recruitment.rpa.status import inspect_boss_status


class WorkerApiClient:
    def __init__(self, base_url, token, worker_key):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.worker_key = worker_key

    def _request(self, path, payload):
        body = dict(payload)
        body["worker_key"] = self.worker_key
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-RPA-Worker-Token": self.token},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"Worker API 请求失败：{exc}") from exc

    def heartbeat(self, payload):
        return self._request("heartbeat/", payload)

    def lease(self):
        return self._request("tasks/lease/", {})

    def event(self, task_id, payload):
        return self._request(f"tasks/{task_id}/event/", payload)

    def complete(self, task_id, payload):
        return self._request(f"tasks/{task_id}/complete/", payload)


def execute_check_status(task, account, runner):
    if task.get("open_login"):
        runner.login(account)
    observed = inspect_boss_status(account.cdp_port)
    result = {
        "login_status": observed.login_status,
        "verification_status": observed.verification_status,
        "detail": observed.detail,
    }
    task_status = "succeeded" if observed.login_status == "ready" else "waiting_human"
    return {"status": task_status, "result": result}


def execute_sync_positions(task, account, runner):
    rows = runner.positions(account)
    return {"status": "succeeded", "result": {"positions": rows}}


EXECUTORS = {
    "check_status": execute_check_status,
    "sync_positions": execute_sync_positions,
}


class WorkerEngine:
    def __init__(self, api, runner, worker_key):
        self.api = api
        self.runner = runner
        self.worker_key = worker_key

    def _execute(self, task, account):
        return EXECUTORS[task["action"]](task, account, self.runner)

    def execute_task(self, task):
        if task.get("action") not in EXECUTORS:
            outcome = {"status": "failed", "result": {}, "error_code": "unsupported_action", "error_message": "不支持的自动化动作"}
            self.api.complete(task["id"], outcome)
            return outcome
        browser = task["browser"]
        account = CliAccountConfig(browser["executable"], browser["user_data_dir"], int(browser["cdp_port"]))
        try:
            self.api.event(task["id"], {"event": "started", "message": "本机 Worker 开始执行"})
            with ProfileLock(account.user_data_dir):
                outcome = self._execute(task, account)
        except ProfileLockedError as exc:
            outcome = {"status": "failed", "result": {}, "error_code": "profile_locked", "error_message": str(exc)}
        except BossCliError as exc:
            outcome = {"status": "failed", "result": {}, "error_code": "boss_cli_error", "error_message": str(exc)}
        except Exception as exc:
            outcome = {"status": "failed", "result": {}, "error_code": "worker_error", "error_message": str(exc)}
        self.api.complete(task["id"], outcome)
        return outcome

    def run_once(self):
        leased = self.api.lease()
        task = leased.get("task")
        if task:
            self.execute_task(task)
            return True
        return False


class Command(BaseCommand):
    help = "运行本机 BOSS 只读 RPA Worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        worker_key = f"local-{socket.gethostname().lower()}"
        runner = BossCliRunner()
        api = WorkerApiClient(settings.RPA_API_BASE_URL, settings.RPA_WORKER_TOKEN, worker_key)
        version = runner.version().splitlines()[0]
        heartbeat = {"hostname": socket.gethostname(), "version": version, "capabilities": {"boss_cli": True}}
        api.heartbeat(heartbeat)
        engine = WorkerEngine(api, runner, worker_key)
        if options["once"]:
            engine.run_once()
            return
        stop = threading.Event()
        next_heartbeat = time.monotonic() + 15
        try:
            while not stop.is_set():
                if time.monotonic() >= next_heartbeat:
                    api.heartbeat(heartbeat)
                    next_heartbeat = time.monotonic() + 15
                engine.run_once()
                stop.wait(settings.RPA_POLL_SECONDS)
        except KeyboardInterrupt:
            stop.set()
