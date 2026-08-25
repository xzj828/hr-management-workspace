import json
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand

from recruitment.rpa.browser import ProfileLock, ProfileLockedError
from recruitment.rpa.capabilities import capability_payload
from recruitment.rpa.cli import BossCliError, BossCliRunner, CliAccountConfig
from recruitment.rpa.status import inspect_boss_status
from recruitment.rpa.conversations import parse_chat_messages, parse_conversation_list
from recruitment.rpa.playwright_adapter import BrowserConnectionError, BrowserInventory


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

    def _get(self, path):
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            headers={"X-RPA-Worker-Token": self.token},
            method="GET",
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

    def status_targets(self):
        return self._get("status-targets/")

    def submit_status_observations(self, observations):
        return self._request("status-observations/", {"observations": observations})


class AccountStatusObserver:
    def __init__(self, api, interval=30):
        self.api = api
        self.interval = interval

    def run_once(self):
        observations = []
        for target in self.api.status_targets().get("accounts", []):
            observed = inspect_boss_status(target["browser"]["cdp_port"])
            observations.append({
                "account_id": target["id"],
                "login_status": observed.login_status,
                "verification_status": observed.verification_status,
                "detail": observed.detail,
            })
        if observations:
            self.api.submit_status_observations(observations)
        return observations

    def run(self, stop):
        while not stop.is_set():
            try:
                self.run_once()
            except RuntimeError:
                pass
            stop.wait(self.interval)


def execute_check_status(task, account, runner):
    if task.get("open_login"):
        runner.login(account)
        observed = None
        for attempt in range(10):
            observed = inspect_boss_status(account.cdp_port)
            if observed.login_status != "browser_stopped" or attempt == 9:
                break
            time.sleep(0.5)
    else:
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


def execute_recommend_candidates(task, account, runner):
    payload = task.get("request_payload") or {}
    rows = runner.recommend(account, str(payload.get("job_title", "")))
    return {"status": "succeeded", "result": {"candidates": rows}}


def execute_search_candidates(task, account, runner):
    payload = task.get("request_payload") or {}
    rows = runner.search(account, str(payload.get("keyword", "")))
    return {"status": "succeeded", "result": {"candidates": rows}}


def execute_deep_match(task, account, runner):
    payload = task.get("request_payload") or {}
    rows = runner.deep_search(
        account,
        job=str(payload.get("job_title", "")),
        core=payload.get("core") if isinstance(payload.get("core"), list) else [],
        bonus=payload.get("bonus") if isinstance(payload.get("bonus"), list) else [],
        match=True,
    )
    return {"status": "succeeded", "result": {"candidates": rows}}


def _safe_target(task):
    payload = task.get("request_payload") or {}
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    name = str(target.get("name", "")).strip()
    identity = str(target.get("external_id") or target.get("fingerprint") or "").strip()
    if not name or not identity:
        return payload, target, None
    return payload, target, name


def execute_greet(task, account, runner):
    payload, target, name = _safe_target(task)
    fingerprint = str(target.get("fingerprint", "")).strip()
    job_title = str(target.get("job_title", "")).strip()
    if not name or not fingerprint:
        return {
            "status": "waiting_human", "result": {}, "error_code": "target_identity_missing",
            "error_message": "候选人缺少可复核身份，请由 HR 人工确认",
        }
    refreshed = runner.recommend(account, job_title)
    from recruitment.services.discovery import _fingerprint

    account_id = target.get("boss_account_id")
    same_name = [row for row in refreshed if row.get("display_name") == name]
    matches = [
        row for row in refreshed
        if row.get("display_name") == name
        and (row.get("fingerprint") == fingerprint or (account_id and _fingerprint(account_id, row) == fingerprint))
    ]
    if len(matches) != 1 or len(same_name) != 1:
        return {
            "status": "waiting_human", "result": {}, "error_code": "target_identity_ambiguous",
            "error_message": "刷新后无法唯一确认候选人，已禁止发送",
        }
    runner.greet(account, name, job=job_title)
    return {"status": "succeeded", "result": {"verified": True, "target_name": name}}


def execute_request_resume(task, account, runner):
    payload, target, name = _safe_target(task)
    if not name:
        return {"status": "waiting_human", "result": {}, "error_code": "target_identity_missing", "error_message": "候选人身份不足"}
    runner.request_resume(
        account,
        name,
        message=str(payload.get("message", "")),
        first_contact=bool(payload.get("first_contact", False)),
    )
    return {"status": "succeeded", "result": {"verified": True, "target_name": name}}


def execute_send_interview(task, account, runner):
    payload, target, name = _safe_target(task)
    message = str(payload.get("message", "")).strip()
    if not name or not message:
        return {"status": "waiting_human", "result": {}, "error_code": "target_identity_missing", "error_message": "候选人身份或邀约内容不足"}
    runner.send_text(account, name, message)
    return {"status": "succeeded", "result": {"verified": True, "target_name": name}}


def execute_sync_conversations(task, account, runner):
    rows = parse_conversation_list(runner.conversations(account))
    incoming = Path(settings.MEDIA_ROOT) / "rpa-incoming"
    name_counts = {row["name"]: sum(1 for item in rows if item["name"] == row["name"]) for row in rows}
    for row in rows[:50]:
        if name_counts[row["name"]] != 1:
            row["sync_error"] = "同名候选人不唯一，未打开会话"
            continue
        try:
            opened = runner.open_chat(account, row["name"])
            row["messages"] = parse_chat_messages(opened.stdout)
            row["attachments"] = BrowserInventory(account.cdp_port).download_resume_attachments(row["name"], incoming)
        except (BossCliError, BrowserConnectionError) as exc:
            row["sync_error"] = str(exc)
    return {"status": "succeeded", "result": {"conversations": rows}}


def execute_view_online_resume(task, account, runner):
    payload, target, name = _safe_target(task)
    if not name:
        return {"status": "waiting_human", "result": {}, "error_code": "target_identity_missing", "error_message": "候选人身份不足"}
    runner.preview(account, name)
    incoming = Path(settings.MEDIA_ROOT) / "rpa-incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    output_path = incoming / f"online-resume-{uuid.uuid4().hex}.pdf"
    BrowserInventory(account.cdp_port).save_pdf(name, output_path)
    return {
        "status": "succeeded",
        "result": {"verified": True, "pdf_path": str(output_path), "filename": f"{name}-在线简历.pdf"},
    }


def _preview_image_path(output):
    match = re.search(r"(?:简历预览截图|resume(?: preview)? screenshot)\s*[:：]\s*(.+?\.png)\s*$", str(output or ""), re.I | re.M)
    if not match:
        raise BossCliError("BOSS CLI 未返回在线简历截图路径")
    path = Path(match.group(1).strip().strip('"')).resolve(strict=True)
    if path.suffix.lower() != ".png":
        raise BossCliError("BOSS CLI 返回的在线简历格式无效")
    return path


def execute_search_pull_resumes(task, account, runner):
    payload = task.get("request_payload") or {}
    source = str(payload.get("source", "recommend"))
    criteria = payload.get("criteria") if isinstance(payload.get("criteria"), dict) else {}
    if source == "search":
        rows = runner.search(account, str(criteria.get("keyword", "")))
    elif source == "deep_search":
        rows = runner.deep_search(
            account, job=str(payload.get("job_title", "")),
            core=criteria.get("core") if isinstance(criteria.get("core"), list) else [],
            bonus=criteria.get("bonus") if isinstance(criteria.get("bonus"), list) else [], match=True,
        )
    else:
        rows = runner.recommend(account, str(payload.get("job_title", "")))
    max_scan = max(1, min(int(payload.get("max_scan_count", 1)), 100))
    target = max(1, min(int(payload.get("target_resume_count", 1)), max_scan))
    scanned = rows[:max_scan]
    incoming = Path(settings.MEDIA_ROOT) / "rpa-incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    pulled = []
    errors = []
    seen_names = set()
    for row in scanned:
        name = str(row.get("display_name", "")).strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        try:
            preview = runner.preview(account, name)
            source_path = _preview_image_path(preview.stdout)
            output_path = incoming / f"online-resume-{uuid.uuid4().hex}.png"
            shutil.copy2(source_path, output_path)
            pulled.append({"candidate": row, "path": str(output_path), "filename": f"{name}-在线简历.png"})
            if len(pulled) >= target:
                break
        except (BossCliError, OSError) as exc:
            errors.append({"name": name, "error": str(exc)})
    return {
        "status": "succeeded",
        "result": {"candidates": scanned, "resumes": pulled, "scanned_count": len(scanned), "errors": errors},
    }


EXECUTORS = {
    "check_status": execute_check_status,
    "sync_positions": execute_sync_positions,
    "recommend_candidates": execute_recommend_candidates,
    "search_candidates": execute_search_candidates,
    "deep_match": execute_deep_match,
    "greet": execute_greet,
    "request_resume": execute_request_resume,
    "send_interview": execute_send_interview,
    "sync_conversations": execute_sync_conversations,
    "view_online_resume": execute_view_online_resume,
    "search_pull_resumes": execute_search_pull_resumes,
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
        except BrowserConnectionError as exc:
            outcome = {"status": "waiting_human", "result": {}, "error_code": "browser_identity_check", "error_message": str(exc)}
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
        heartbeat = {
            "hostname": socket.gethostname(),
            "version": version,
            "capabilities": {"boss_cli": True, "actions": capability_payload()},
        }
        api.heartbeat(heartbeat)
        engine = WorkerEngine(api, runner, worker_key)
        observer = AccountStatusObserver(api)
        if options["once"]:
            observer.run_once()
            engine.run_once()
            return
        stop = threading.Event()
        observer_thread = threading.Thread(target=observer.run, args=(stop,), name="boss-status-observer", daemon=True)
        observer_thread.start()
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
        finally:
            stop.set()
            observer_thread.join(timeout=2)
