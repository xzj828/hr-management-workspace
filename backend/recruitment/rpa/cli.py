import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from recruitment.rpa.candidates import deep_search_args, parse_candidate_output


MAX_OUTPUT_CHARS = 32 * 1024


class BossCliError(RuntimeError):
    pass


class BossCliTimeout(BossCliError):
    pass


@dataclass(frozen=True)
class CliAccountConfig:
    executable: str
    user_data_dir: str
    cdp_port: int


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str


def _decode_output(value):
    if isinstance(value, str):
        return value[:MAX_OUTPUT_CHARS]
    for encoding, errors in (("utf-8", "strict"), ("gb18030", "strict"), ("utf-8", "replace")):
        try:
            return (value or b"").decode(encoding, errors=errors)[:MAX_OUTPUT_CHARS]
        except UnicodeDecodeError:
            continue
    return ""


def parse_positions(output):
    rows = []
    for raw_line in output.splitlines():
        match = re.match(r"^\s*\d+\.\s+(.+)$", raw_line)
        if not match:
            continue
        normalized = " ".join(raw_line.split())
        parts = [part.strip() for part in match.group(1).split("｜")]
        title = parts[0]
        state = ""
        external_id = ""
        for part in parts[1:]:
            if part.startswith("状态:") or part.startswith("状态："):
                state = re.split("[:：]", part, maxsplit=1)[1].strip()
            elif part.startswith("ID:") or part.startswith("ID："):
                external_id = re.split("[:：]", part, maxsplit=1)[1].strip()
        if not external_id:
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
            external_id = f"derived-{digest}"
        status = "open" if state == "开放中" else "closed" if state == "已关闭" else "paused"
        rows.append({
            "external_id": external_id,
            "title": title,
            "status": status,
            "raw": raw_line.strip(),
        })
    return rows


class BossCliRunner:
    ALLOWED = {
        "--version", "login", "positions", "recommend", "search", "deep-search",
        "list", "chat", "greet", "send", "action", "preview",
    }

    def __init__(self, cli_path=None):
        self.cli_path = cli_path or self._discover()

    @staticmethod
    def _discover():
        configured = os.environ.get("BOSS_CLI")
        if configured and Path(configured).exists():
            return configured
        for command in ("boss", "boss-cli"):
            found = shutil.which(command)
            if found:
                return found
        raise BossCliError("未找到 boss-cli，请先安装并配置 BOSS_CLI")

    @staticmethod
    def _account_env(account):
        env = os.environ.copy()
        env.update({
            "CHROME_PATH": account.executable,
            "BOSS_BROWSER_USER_DATA_DIR": account.user_data_dir,
            "BOSS_BROWSER_REMOTE_DEBUGGING_PORT": str(account.cdp_port),
            "BOSS_BROWSER_HEADLESS": "false",
        })
        return env

    def _run(self, args, *, env, timeout_seconds):
        args = [args] if isinstance(args, str) else [str(value) for value in args]
        if not args or args[0] not in self.ALLOWED:
            raise BossCliError("不支持的 boss-cli 命令")
        if any("\x00" in value or "\r" in value or "\n" in value for value in args):
            raise BossCliError("boss-cli 参数包含非法字符")
        try:
            completed = subprocess.run(
                [self.cli_path, *args],
                shell=False,
                capture_output=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise BossCliTimeout(f"boss-cli 执行超时：{args[0]}") from exc
        except OSError as exc:
            raise BossCliError(f"boss-cli 无法启动：{exc}") from exc

        result = CliResult(
            returncode=completed.returncode,
            stdout=_decode_output(completed.stdout),
            stderr=_decode_output(completed.stderr),
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
            raise BossCliError(detail)
        return result

    def version(self):
        return self._run(["--version"], env=os.environ.copy(), timeout_seconds=20).stdout.strip()

    def login(self, account):
        return self._run(["login"], env=self._account_env(account), timeout_seconds=90)

    def positions(self, account):
        result = self._run(["positions"], env=self._account_env(account), timeout_seconds=180)
        return parse_positions(result.stdout)

    def recommend(self, account, job_keyword=""):
        keyword = str(job_keyword or "").strip()
        args = ["recommend", keyword] if keyword else ["recommend"]
        result = self._run(args, env=self._account_env(account), timeout_seconds=180)
        return parse_candidate_output(result.stdout, source="recommend")

    def search(self, account, keyword=""):
        keyword = str(keyword or "").strip()
        if len(keyword) > 20:
            raise BossCliError("常规搜索关键词最多 20 个字符")
        args = ["search", keyword] if keyword else ["search"]
        result = self._run(args, env=self._account_env(account), timeout_seconds=180)
        return parse_candidate_output(result.stdout, source="search")

    def deep_search(self, account, *, job="", core=None, bonus=None, match=False):
        values = [str(job or ""), *(core or []), *(bonus or [])]
        if any(len(str(value).strip()) > 200 for value in values):
            raise BossCliError("深度搜索单项条件最多 200 个字符")
        args = deep_search_args(job=job, core=core, bonus=bonus, match=match)
        result = self._run(args, env=self._account_env(account), timeout_seconds=240)
        return parse_candidate_output(result.stdout, source="deep_search") if match else []

    def conversations(self, account, *, unread=False):
        args = ["list", "--unread"] if unread else ["list"]
        return self._run(args, env=self._account_env(account), timeout_seconds=120).stdout

    def open_chat(self, account, name):
        normalized = str(name or "").strip()
        if not normalized or len(normalized) > 100:
            raise BossCliError("候选人名称无效")
        return self._run(
            ["chat", normalized, "--strict"], env=self._account_env(account), timeout_seconds=120
        )

    def greet(self, account, name, *, job=""):
        normalized = str(name or "").strip()
        job_name = str(job or "").strip()
        if not normalized or len(normalized) > 100 or len(job_name) > 120:
            raise BossCliError("打招呼目标无效")
        args = ["greet", normalized]
        if job_name:
            args.extend(["--job", job_name])
        return self._run(args, env=self._account_env(account), timeout_seconds=120)

    def request_resume(self, account, name, *, message="", first_contact=False):
        self.open_chat(account, name)
        if first_contact:
            normalized = str(message or "").strip()
            if not normalized or len(normalized) > 1000 or "\n" in normalized or "\r" in normalized:
                raise BossCliError("首次联系求简历必须提供 1 到 1000 个字符的单行话术")
            return self._run(
                ["send", "--text", normalized, "--request-resume"],
                env=self._account_env(account),
                timeout_seconds=120,
            )
        return self._run(
            ["action", "request-attachment-resume"],
            env=self._account_env(account),
            timeout_seconds=120,
        )

    def send_text(self, account, name, message):
        normalized = str(message or "").strip()
        if not normalized or len(normalized) > 1000 or "\n" in normalized or "\r" in normalized:
            raise BossCliError("发送内容必须为 1 到 1000 个字符的单行文本")
        self.open_chat(account, name)
        return self._run(
            ["send", "--text", normalized], env=self._account_env(account), timeout_seconds=120
        )

    def preview(self, account, name):
        normalized = str(name or "").strip()
        if not normalized or len(normalized) > 100:
            raise BossCliError("在线简历目标无效")
        return self._run(["preview", normalized], env=self._account_env(account), timeout_seconds=120)

