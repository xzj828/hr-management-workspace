import json
import re
import shutil
import socket
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand

from recruitment.rpa.browser import (
    BrowserUnavailableError,
    ProfileLock,
    ProfileLockedError,
    cdp_is_running,
    managed_cdp_matches,
    record_managed_cdp,
)
from recruitment.rpa.capabilities import capability_payload
from recruitment.rpa.cli import BossCliError, BossCliRunner, CliAccountConfig
from recruitment.rpa.status import inspect_boss_status
from recruitment.rpa.conversations import parse_chat_messages, parse_conversation_list
from recruitment.rpa.playwright_adapter import BrowserConnectionError, BrowserInventory


HEARTBEAT_INTERVAL_SECONDS = 15
MAX_API_RETRY_SECONDS = 30


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
            observed = inspect_boss_status(
                target["browser"]["cdp_port"],
                user_data_dir=target["browser"]["user_data_dir"],
            )
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


class WorkerHeartbeat:
    def __init__(self, api, payload, *, interval=HEARTBEAT_INTERVAL_SECONDS, stderr=None):
        self.api = api
        self.payload = payload
        self.interval = interval
        self.stderr = stderr

    def run(self, stop):
        retry_seconds = 1
        while not stop.is_set():
            try:
                self.api.heartbeat(self.payload)
            except RuntimeError as exc:
                if self.stderr is not None:
                    self.stderr.write(f"Worker 心跳暂时失败，{retry_seconds} 秒后重试：{exc}")
                stop.wait(retry_seconds)
                retry_seconds = min(retry_seconds * 2, MAX_API_RETRY_SECONDS)
                continue
            retry_seconds = 1
            stop.wait(self.interval)


def execute_check_status(task, account, runner):
    if task.get("open_login"):
        browser_was_running = cdp_is_running(account.cdp_port)
        if browser_was_running and not managed_cdp_matches(account.cdp_port, account.user_data_dir):
            return {
                "status": "failed",
                "result": {"login_status": "error", "verification_status": "cdp_identity_mismatch", "detail": "调试端口不属于该账号的隔离浏览器"},
                "error_code": "cdp_identity_mismatch",
                "error_message": "调试端口不属于该账号的隔离浏览器",
            }
        login_process = None
        try:
            if hasattr(runner, "start_login"):
                login_process = runner.start_login(account)
            else:
                runner.login(account)
            observed = None
            for attempt in range(20):
                if cdp_is_running(account.cdp_port) and not browser_was_running:
                    try:
                        record_managed_cdp(account.cdp_port, account.user_data_dir)
                        browser_was_running = True
                    except BrowserUnavailableError:
                        pass
                observed = inspect_boss_status(
                    account.cdp_port,
                    user_data_dir=account.user_data_dir,
                )
                if observed.login_status != "browser_stopped" and not browser_was_running:
                    try:
                        record_managed_cdp(account.cdp_port, account.user_data_dir)
                        browser_was_running = True
                    except BrowserUnavailableError:
                        pass
                if (observed.login_status != "browser_stopped" and browser_was_running) or attempt == 19:
                    break
                if login_process is not None and login_process.poll() is not None:
                    break
                time.sleep(0.5)
        finally:
            if login_process is not None:
                runner.stop_login(login_process)
    else:
        observed = inspect_boss_status(account.cdp_port, user_data_dir=account.user_data_dir)
    result = {
        "login_status": observed.login_status,
        "verification_status": observed.verification_status,
        "detail": observed.detail,
    }
    if observed.login_status == "waiting_human":
        return {"status": "waiting_human", "result": result}
    if task.get("open_login") and observed.login_status in {"browser_stopped", "error"}:
        return {
            "status": "failed",
            "result": result,
            "error_code": "browser_login_unavailable",
            "error_message": observed.detail or "隔离浏览器登录状态不可用",
        }
    return {"status": "succeeded", "result": result}


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


def _candidate_rows_for_verification(*, runner, account, source, job_title, criteria):
    if source == "search":
        return runner.search(account, str(criteria.get("keyword", "")))
    if source == "deep_search":
        return runner.deep_search(
            account,
            job=str(job_title or ""),
            core=criteria.get("core") if isinstance(criteria.get("core"), list) else [],
            bonus=criteria.get("bonus") if isinstance(criteria.get("bonus"), list) else [],
            match=True,
        )
    if source == "recommend":
        return runner.recommend(account, str(job_title or ""))
    raise BossCliError("候选人身份复核来源无效")


def _verified_candidate_row(*, rows, target, account_id):
    from recruitment.services.discovery import _fingerprint

    name = str(target.get("name") or target.get("display_name") or "").strip()
    expected = str(target.get("fingerprint") or "").strip()
    if not name or not expected or not account_id:
        return None
    same_name = [row for row in rows if str(row.get("display_name", "")).strip() == name]
    matches = [row for row in same_name if _fingerprint(account_id, row) == expected]
    if len(same_name) != 1 or len(matches) != 1:
        return None
    return matches[0]


def _verify_conversation_target(*, runner, account, target):
    name = str(target.get("name", "")).strip()
    external_id = str(target.get("external_id", "")).strip()
    if not name or not external_id:
        return None
    rows = parse_conversation_list(runner.conversations(account))
    same_name = [row for row in rows if str(row.get("name", "")).strip() == name]
    if len(same_name) != 1:
        return None
    refreshed = same_name[0]
    return refreshed if str(refreshed.get("external_id", "")).strip() == external_id else None


def execute_greet(task, account, runner):
    payload, target, name = _safe_target(task)
    fingerprint = str(target.get("fingerprint", "")).strip()
    external_id = str(target.get("external_id", "")).strip()
    job_title = str(target.get("job_title", "")).strip()
    stable_action = getattr(runner, "greet_by_external_id", None)
    if not name or not fingerprint or not external_id or not callable(stable_action):
        return {
            "status": "waiting_human", "result": {}, "error_code": "stable_identity_action_unavailable",
            "error_message": "当前 BOSS 适配器不能按平台稳定 ID 打招呼，请由 HR 人工处理",
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
    if (
        len(matches) != 1
        or len(same_name) != 1
        or str(matches[0].get("external_id", "")).strip() != external_id
    ):
        return {
            "status": "waiting_human", "result": {}, "error_code": "target_identity_ambiguous",
            "error_message": "刷新后无法唯一确认候选人，已禁止发送",
        }
    stable_action(account, external_id, job=job_title)
    return {
        "status": "succeeded",
        "result": {
            "verified": True,
            "target_name": name,
            "expected_external_id": external_id,
            "observed_external_id": str(matches[0].get("external_id", "")).strip(),
        },
    }


def execute_request_resume(task, account, runner):
    payload, target, name = _safe_target(task)
    external_id = str(target.get("external_id", "")).strip()
    if not name or not external_id:
        return {"status": "waiting_human", "result": {}, "error_code": "target_identity_missing", "error_message": "候选人缺少平台稳定 ID"}
    refreshed = _verify_conversation_target(runner=runner, account=account, target=target)
    if refreshed is None:
        return {
            "status": "waiting_human",
            "result": {},
            "error_code": "target_identity_ambiguous",
            "error_message": "刷新沟通列表后无法唯一确认候选人，已禁止索要简历",
        }
    stable_action = getattr(runner, "request_resume_by_external_id", None)
    if not callable(stable_action):
        return {
            "status": "waiting_human",
            "result": {"verified": True, "external_id": external_id},
            "error_code": "stable_identity_action_unavailable",
            "error_message": "当前 BOSS 适配器只能按姓名索要简历，请由 HR 人工处理",
        }
    stable_action(
        account,
        external_id,
        message=str(payload.get("message", "")),
        first_contact=bool(payload.get("first_contact", False)),
    )
    return {
        "status": "succeeded",
        "result": {
            "verified": True,
            "target_name": name,
            "conversation_index": refreshed.get("index"),
            "expected_external_id": external_id,
            "observed_external_id": str(refreshed.get("external_id", "")).strip(),
        },
    }


def execute_send_interview(task, account, runner):
    payload, target, name = _safe_target(task)
    external_id = str(target.get("external_id", "")).strip()
    message = str(payload.get("message", "")).strip()
    if not name or not external_id or not message:
        return {"status": "waiting_human", "result": {}, "error_code": "target_identity_missing", "error_message": "候选人平台稳定 ID 或邀约内容不足"}
    refreshed = _verify_conversation_target(runner=runner, account=account, target=target)
    stable_action = getattr(runner, "send_text_by_external_id", None)
    if refreshed is None or not callable(stable_action):
        return {
            "status": "waiting_human", "result": {},
            "error_code": "stable_identity_action_unavailable",
            "error_message": "当前 BOSS 适配器不能按平台稳定 ID 发送邀约，请由 HR 人工处理",
        }
    stable_action(account, external_id, message)
    return {
        "status": "succeeded",
        "result": {
            "verified": True,
            "target_name": name,
            "expected_external_id": external_id,
            "observed_external_id": str(refreshed.get("external_id", "")).strip(),
        },
    }


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
    external_id = str(target.get("external_id", "")).strip()
    stable_action = getattr(runner, "preview_by_external_id", None)
    if not name or not external_id or not callable(stable_action):
        return {
            "status": "waiting_human", "result": {},
            "error_code": "stable_identity_action_unavailable",
            "error_message": "当前 BOSS 适配器不能按平台稳定 ID 查看在线简历，请由 HR 人工处理",
        }
    verification = target.get("verification") if isinstance(target.get("verification"), dict) else {}
    rows = _candidate_rows_for_verification(
        runner=runner,
        account=account,
        source=str(verification.get("source", "")),
        job_title=target.get("job_title", ""),
        criteria=verification.get("criteria") if isinstance(verification.get("criteria"), dict) else {},
    ) if verification else []
    verified = _verified_candidate_row(
        rows=rows,
        target=target,
        account_id=target.get("boss_account_id"),
    )
    if verified is None or str(verified.get("external_id", "")).strip() != external_id:
        return {
            "status": "waiting_human",
            "result": {},
            "error_code": "target_identity_ambiguous",
            "error_message": "刷新候选人来源后无法唯一确认目标，已禁止查看在线简历",
        }
    preview = stable_action(account, external_id)
    source_path = _preview_image_path(preview.stdout)
    incoming = Path(settings.MEDIA_ROOT) / "rpa-incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    output_path = incoming / f"online-resume-{uuid.uuid4().hex}.png"
    shutil.copy2(source_path, output_path)
    return {
        "status": "succeeded",
        "result": {
            "verified": True,
            "image_path": str(output_path),
            "filename": f"{name}-在线简历.png",
            "identity_fingerprint": target.get("fingerprint"),
            "expected_external_id": external_id,
            "observed_external_id": str(verified.get("external_id", "")).strip(),
        },
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
    account_id = payload.get("boss_account_id")
    budget = int(payload.get("resume_view_budget", 0) or 0)
    if not account_id or budget < 1:
        return {
            "status": "waiting_human",
            "result": {},
            "error_code": "approval_scope_missing",
            "error_message": "主动寻访缺少已确认的账号或简历查看额度",
        }
    rows = _candidate_rows_for_verification(
        runner=runner,
        account=account,
        source=source,
        job_title=payload.get("job_title", ""),
        criteria=criteria,
    )
    max_scan = max(1, min(int(payload.get("max_scan_count", 1)), 100))
    target = max(1, min(int(payload.get("target_resume_count", 1)), max_scan))
    scanned = rows[:max_scan]
    incoming = Path(settings.MEDIA_ROOT) / "rpa-incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    pulled = []
    errors = []
    attempts = []
    seen_identities = set()
    view_attempt_count = 0
    manual_intervention_required = False
    stable_preview = getattr(runner, "preview_by_external_id", None)
    from recruitment.services.discovery import _fingerprint

    for row in scanned:
        name = str(row.get("display_name", "")).strip()
        expected_external_id = str(row.get("external_id", "")).strip()
        fingerprint = _fingerprint(account_id, row) if name else ""
        if not name or fingerprint in seen_identities:
            continue
        seen_identities.add(fingerprint)
        refreshed_rows = _candidate_rows_for_verification(
            runner=runner,
            account=account,
            source=source,
            job_title=payload.get("job_title", ""),
            criteria=criteria,
        )
        verified = _verified_candidate_row(
            rows=refreshed_rows,
            target={"name": name, "fingerprint": fingerprint},
            account_id=account_id,
        )
        if verified is None:
            error = "刷新后身份不唯一，未打开在线简历"
            errors.append({"name": name, "error": error})
            attempts.append({
                "sequence": len(attempts) + 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "name": name,
                "fingerprint": fingerprint,
                "verified": False,
                "preview_attempted": False,
                "outcome": "identity_ambiguous",
                "error_code": "identity_ambiguous",
                "expected_external_id": expected_external_id,
                "observed_external_id": "",
                "error": error,
            })
            continue
        external_id = str(verified.get("external_id", "")).strip()
        verified_name = str(verified.get("display_name", "")).strip()
        verified_fingerprint = _fingerprint(account_id, verified)
        if not external_id:
            error = "候选人缺少平台稳定 ID，在线简历查看已转人工"
            errors.append({"name": name, "error": error})
            attempts.append({
                "sequence": len(attempts) + 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "name": verified_name,
                "fingerprint": verified_fingerprint,
                "verified": False,
                "preview_attempted": False,
                "outcome": "target_identity_unverifiable",
                "error_code": "target_identity_unverifiable",
                "expected_external_id": expected_external_id,
                "observed_external_id": external_id,
                "error": error,
            })
            manual_intervention_required = True
            continue
        if not callable(stable_preview):
            error = "当前 BOSS 适配器只能按姓名查看在线简历，已转人工"
            errors.append({"name": name, "error": error})
            attempts.append({
                "sequence": len(attempts) + 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "name": verified_name,
                "fingerprint": verified_fingerprint,
                "verified": True,
                "preview_attempted": False,
                "outcome": "stable_action_unavailable",
                "error_code": "stable_action_unavailable",
                "expected_external_id": expected_external_id,
                "observed_external_id": external_id,
                "error": error,
            })
            manual_intervention_required = True
            continue
        if view_attempt_count >= budget:
            break
        view_attempt_count += 1
        attempt = {
            "sequence": len(attempts) + 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "name": verified_name,
            "fingerprint": verified_fingerprint,
            "verified": True,
            "preview_attempted": True,
            "outcome": "preview_failed",
            "error_code": "preview_failed",
            "expected_external_id": expected_external_id,
            "observed_external_id": external_id,
            "error": "",
        }
        try:
            preview = stable_preview(account, external_id)
            source_path = _preview_image_path(preview.stdout)
            output_path = incoming / f"online-resume-{uuid.uuid4().hex}.png"
            shutil.copy2(source_path, output_path)
            pulled.append({
                "candidate": verified,
                "identity_snapshot": {
                    "name": verified_name,
                    "external_id": str(verified.get("external_id", "")),
                    "fingerprint": verified_fingerprint,
                    "verified": True,
                    "expected_external_id": expected_external_id,
                    "observed_external_id": external_id,
                },
                "path": str(output_path),
                "filename": f"{verified_name}-在线简历.png",
            })
            attempt["outcome"] = "preview_succeeded"
            attempt["error_code"] = ""
            if len(pulled) >= target:
                attempts.append(attempt)
                break
        except Exception as exc:
            attempt["error"] = str(exc)[:1000]
            errors.append({"name": name, "error": attempt["error"]})
        attempts.append(attempt)
    return {
        "status": "waiting_human" if manual_intervention_required and len(pulled) < target else "succeeded",
        "result": {
            "candidates": scanned,
            "resumes": pulled,
            "scanned_count": len(scanned),
            "view_attempt_count": view_attempt_count,
            "resume_view_budget": budget,
            "attempts": attempts,
            "errors": errors,
        },
        **({
            "error_code": "stable_identity_action_unavailable",
            "error_message": "在线简历查看需要按平台稳定 ID 原子执行，当前适配器不支持",
        } if manual_intervention_required and len(pulled) < target else {}),
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
        is_open_login = (
            task.get("action") == "check_status"
            and task.get("open_login") is True
        )
        try:
            self.api.event(task["id"], {"event": "started", "message": "本机 Worker 开始执行"})
            with ProfileLock(account.user_data_dir):
                if not is_open_login and not managed_cdp_matches(account.cdp_port, account.user_data_dir):
                    outcome = {
                        "status": "failed",
                        "result": {},
                        "error_code": "cdp_identity_mismatch",
                        "error_message": "隔离浏览器实例与任务账号不匹配，请重新打开该账号登录窗口",
                    }
                elif task.get("action") != "check_status":
                    observed = inspect_boss_status(
                        account.cdp_port,
                        user_data_dir=account.user_data_dir,
                    )
                    if observed.login_status != "ready":
                        outcome = {
                            "status": "failed",
                            "result": {
                                "login_status": observed.login_status,
                                "verification_status": observed.verification_status,
                                "detail": observed.detail,
                            },
                            "error_code": "boss_account_not_ready",
                            "error_message": observed.detail or "BOSS 账号当前未登录，请重新打开登录窗口",
                        }
                    else:
                        outcome = self._execute(task, account)
                else:
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


def probe_boss_cli():
    try:
        runner = BossCliRunner()
        raw_version = runner.version().strip()
        if not raw_version:
            raise BossCliError("boss-cli 未返回版本信息")
    except BossCliError as exc:
        return None, "", {
            "code": "boss_cli_unavailable",
            "message": str(exc)[:300],
        }
    return runner, raw_version.splitlines()[0], None


def build_heartbeat(*, hostname, version, cli_error):
    capabilities = {
        "boss_cli": cli_error is None,
        "actions": capability_payload(),
    }
    if cli_error is not None:
        capabilities["boss_cli_error"] = cli_error
    return {
        "hostname": hostname,
        "version": version,
        "capabilities": capabilities,
    }


def run_worker_loop(*, engine, stop, poll_seconds, stderr):
    retry_seconds = 1
    while not stop.is_set():
        try:
            if engine is not None:
                engine.run_once()
        except RuntimeError as exc:
            stderr.write(f"Worker API 暂时不可用，{retry_seconds} 秒后重试：{exc}")
            stop.wait(retry_seconds)
            retry_seconds = min(retry_seconds * 2, MAX_API_RETRY_SECONDS)
            continue
        retry_seconds = 1
        stop.wait(poll_seconds)


class Command(BaseCommand):
    help = "运行本机 BOSS 只读 RPA Worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        worker_key = f"local-{socket.gethostname().lower()}"
        api = WorkerApiClient(settings.RPA_API_BASE_URL, settings.RPA_WORKER_TOKEN, worker_key)
        runner, version, cli_error = probe_boss_cli()
        heartbeat = build_heartbeat(
            hostname=socket.gethostname(),
            version=version,
            cli_error=cli_error,
        )
        engine = WorkerEngine(api, runner, worker_key) if runner is not None else None
        observer = AccountStatusObserver(api)
        if options["once"]:
            api.heartbeat(heartbeat)
            observer.run_once()
            if engine is not None:
                engine.run_once()
            return
        stop = threading.Event()
        heartbeat_sender = WorkerHeartbeat(api, heartbeat, stderr=self.stderr)
        heartbeat_thread = threading.Thread(
            target=heartbeat_sender.run,
            args=(stop,),
            name="rpa-worker-heartbeat",
            daemon=True,
        )
        observer_thread = threading.Thread(target=observer.run, args=(stop,), name="boss-status-observer", daemon=True)
        heartbeat_thread.start()
        observer_thread.start()
        try:
            run_worker_loop(
                engine=engine,
                stop=stop,
                poll_seconds=settings.RPA_POLL_SECONDS,
                stderr=self.stderr,
            )
        except KeyboardInterrupt:
            stop.set()
        finally:
            stop.set()
            heartbeat_thread.join(timeout=2)
            observer_thread.join(timeout=2)
