import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from recruitment.rpa.candidates import deep_search_args, parse_candidate_output


MAX_OUTPUT_CHARS = 32 * 1024
WINDOWS_SCRIPT_SUFFIXES = {".cmd", ".bat", ".ps1"}
JAVASCRIPT_SUFFIXES = {".js", ".mjs", ".cjs"}

# Do not pass the Django/Worker process environment wholesale to third-party
# automation code. These values are enough for Node and a headed Chromium
# process to locate the current Windows user profile and temporary directory.
BASE_ENVIRONMENT_KEYS = (
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)


class BossCliError(RuntimeError):
    pass


class BossCliTimeout(BossCliError):
    pass


class BossCliCancelled(BossCliError):
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


@dataclass(frozen=True)
class CliInvocation:
    executable: str
    prefix: tuple[str, ...] = ()

    @property
    def command(self):
        return [self.executable, *self.prefix]


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

    def __init__(self, cli_path=None, *, cancel_requested=None):
        self.invocation = self._resolve_configured(cli_path) if cli_path else self._discover()
        self.cancel_requested = cancel_requested
        # Kept as a compatibility/introspection attribute. It is always the
        # native executable (normally node.exe), never a Windows script shim.
        self.cli_path = self.invocation.executable

    def set_cancel_check(self, callback):
        self.cancel_requested = callback

    @staticmethod
    def _environment_value(source, key):
        expected = key.upper()
        for current_key, value in source.items():
            if current_key.upper() == expected:
                return value
        return None

    @classmethod
    def _base_env(cls):
        env = {}
        for key in BASE_ENVIRONMENT_KEYS:
            value = cls._environment_value(os.environ, key)
            if value is not None:
                env[key] = value
        return env

    @staticmethod
    def _clean_path(value, *, label):
        raw = str(value or "").strip()
        if not raw or any(character in raw for character in ("\x00", "\r", "\n")):
            raise BossCliError(f"{label}无效")
        return Path(raw).expanduser().resolve()

    @classmethod
    def _node_invocation(cls, entry, *, node_path=None, require_files):
        entry_path = cls._clean_path(entry, label="boss-cli JavaScript 入口")
        if entry_path.suffix.lower() not in JAVASCRIPT_SUFFIXES:
            raise BossCliError("BOSS_CLI 必须指向安全的 JavaScript 入口或原生可执行文件")
        if require_files and not entry_path.is_file():
            raise BossCliError("boss-cli JavaScript 入口不存在")
        node = cls._discover_node(node_path, require_file=require_files)
        return CliInvocation(str(node), (str(entry_path),))

    @classmethod
    def _native_invocation(cls, executable, *, require_file):
        path = cls._clean_path(executable, label="boss-cli 可执行文件")
        suffix = path.suffix.lower()
        if suffix in WINDOWS_SCRIPT_SUFFIXES:
            raise BossCliError("禁止执行 .cmd、.bat 或 .ps1 的 boss-cli shim")
        if os.name == "nt" and require_file:
            raise BossCliError("Windows 下 BOSS_CLI 必须指向固定的 JavaScript 入口")
        if require_file and not path.is_file():
            raise BossCliError("boss-cli 可执行文件不存在")
        return CliInvocation(str(path))

    @classmethod
    def _resolve_configured(cls, configured, *, require_files=False):
        if isinstance(configured, (list, tuple)):
            values = [str(value) for value in configured]
            if len(values) == 2:
                return cls._node_invocation(
                    values[1], node_path=values[0], require_files=require_files
                )
            if len(values) == 1:
                configured = values[0]
            else:
                raise BossCliError("boss-cli 启动配置无效")
        path = cls._clean_path(configured, label="BOSS_CLI")
        if path.suffix.lower() in JAVASCRIPT_SUFFIXES:
            return cls._node_invocation(
                path,
                node_path=os.environ.get("BOSS_NODE"),
                require_files=require_files,
            )
        return cls._native_invocation(path, require_file=require_files)

    @classmethod
    def _discover_node(cls, configured=None, *, require_file=True):
        if configured:
            path = cls._clean_path(configured, label="Node.js 可执行文件")
            if path.suffix.lower() in WINDOWS_SCRIPT_SUFFIXES:
                raise BossCliError("BOSS_NODE 不能指向 .cmd、.bat 或 .ps1 shim")
            if os.name == "nt" and path.name.lower() != "node.exe":
                raise BossCliError("Windows 下 BOSS_NODE 必须指向 node.exe")
            if require_file and not path.is_file():
                raise BossCliError("BOSS_NODE 指向的 node.exe 不存在")
            return path

        candidates = []
        for environment_key in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)"):
            root = cls._environment_value(os.environ, environment_key)
            if root:
                candidates.append(Path(root) / "nodejs" / "node.exe")
        candidates.extend(filter(None, (shutil.which("node.exe"), shutil.which("node"))))

        for candidate in candidates:
            try:
                path = cls._clean_path(candidate, label="Node.js 可执行文件")
            except (BossCliError, OSError, RuntimeError):
                continue
            if path.suffix.lower() in WINDOWS_SCRIPT_SUFFIXES:
                continue
            if os.name == "nt" and path.name.lower() != "node.exe":
                continue
            if not require_file or path.is_file():
                return path
        raise BossCliError("未找到可信的 node.exe，请安装 Node.js 或配置 BOSS_NODE")

    @classmethod
    def _entry_candidates(cls, node):
        relative = Path("@joohw") / "boss-cli" / "dist" / "cli" / "index.js"
        roots = []
        appdata = cls._environment_value(os.environ, "APPDATA")
        if appdata:
            roots.append(Path(appdata) / "npm" / "node_modules")
        prefix = os.environ.get("NPM_CONFIG_PREFIX")
        if prefix:
            roots.extend((Path(prefix) / "node_modules", Path(prefix) / "lib" / "node_modules"))
        roots.extend((node.parent / "node_modules", node.parent.parent / "lib" / "node_modules"))
        seen = set()
        for root in roots:
            try:
                candidate = (root / relative).resolve()
            except (OSError, RuntimeError):
                continue
            normalized = os.path.normcase(str(candidate))
            if normalized not in seen:
                seen.add(normalized)
                yield candidate

    @classmethod
    def _discover(cls):
        configured = os.environ.get("BOSS_CLI")
        if configured:
            return cls._resolve_configured(configured, require_files=True)
        node = cls._discover_node(os.environ.get("BOSS_NODE"))
        for entry in cls._entry_candidates(node):
            if entry.is_file():
                return CliInvocation(str(node), (str(entry),))
        raise BossCliError(
            "未找到 @joohw/boss-cli JavaScript 入口，请安装固定版本或将 BOSS_CLI 指向 dist/cli/index.js"
        )

    @classmethod
    def _account_env(cls, account):
        env = cls._base_env()
        env.update({
            "CHROME_PATH": account.executable,
            "BOSS_BROWSER_USER_DATA_DIR": account.user_data_dir,
            "BOSS_BROWSER_REMOTE_DEBUGGING_PORT": str(account.cdp_port),
            "BOSS_BROWSER_HEADLESS": "false",
        })
        return env

    def _run(self, args, *, env, timeout_seconds):
        command = self._command(args)
        if callable(self.cancel_requested):
            return self._run_monitored(command, env=env, timeout_seconds=timeout_seconds)
        try:
            completed = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise BossCliTimeout(f"boss-cli 执行超时：{command[len(self.invocation.command)]}") from exc
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

    def _run_monitored(self, command, *, env, timeout_seconds):
        popen_kwargs = {
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as exc:
            raise BossCliError(f"boss-cli 无法启动：{exc}") from exc

        started = time.monotonic()
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if self.cancel_requested():
                    self._stop_command(process)
                    raise BossCliCancelled("任务已按用户要求停止")
                if time.monotonic() - started >= timeout_seconds:
                    self._stop_command(process)
                    raise BossCliTimeout(f"boss-cli 执行超时：{command[len(self.invocation.command)]}")

        result = CliResult(
            returncode=process.returncode,
            stdout=_decode_output(stdout),
            stderr=_decode_output(stderr),
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
            raise BossCliError(detail)
        return result

    @staticmethod
    def _stop_command(process):
        try:
            if process.poll() is not None:
                return
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.communicate(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    return
        except OSError:
            return

    def _command(self, args):
        args = [args] if isinstance(args, str) else [str(value) for value in args]
        if not args or args[0] not in self.ALLOWED:
            raise BossCliError("不支持的 boss-cli 命令")
        if any(
            "\x00" in value
            or "\r" in value
            or "\n" in value
            for value in args
        ):
            raise BossCliError("boss-cli 参数包含非法字符")
        return [*self.invocation.command, *args]

    def _boss_cli_package_root(self):
        if len(self.invocation.prefix) != 1:
            raise BossCliError("Puppeteer 会话桥接需要 @joohw/boss-cli JavaScript 入口")
        entry = Path(self.invocation.prefix[0]).resolve()
        try:
            package_root = entry.parents[2]
        except IndexError as exc:
            raise BossCliError("无法确认 @joohw/boss-cli 安装目录") from exc
        package_json = package_root / "package.json"
        try:
            metadata = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BossCliError("无法读取 @joohw/boss-cli 安装信息") from exc
        if metadata.get("name") != "@joohw/boss-cli" or package_root not in entry.parents:
            raise BossCliError("Puppeteer 会话桥接仅允许使用已配置的 @joohw/boss-cli")
        return package_root

    def _run_chat_bridge(self, account, operation, payload=None, *, timeout_seconds=120):
        bridge = Path(__file__).with_name("boss_chat_bridge.mjs").resolve()
        if not bridge.is_file():
            raise BossCliError("Puppeteer 会话桥接文件不存在")
        request = {
            "operation": str(operation),
            "port": int(account.cdp_port),
            **(payload or {}),
        }
        command = [
            self.invocation.executable,
            str(bridge),
            str(self._boss_cli_package_root()),
        ]
        run_kwargs = {
            "shell": False,
            "capture_output": True,
            "timeout": timeout_seconds,
            "env": self._account_env(account),
            "input": json.dumps(request, ensure_ascii=False).encode("utf-8"),
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            completed = subprocess.run(command, **run_kwargs)
        except subprocess.TimeoutExpired as exc:
            raise BossCliTimeout("Puppeteer 会话桥接执行超时") from exc
        except OSError as exc:
            raise BossCliError(f"Puppeteer 会话桥接无法启动：{exc}") from exc
        stdout = _decode_output(completed.stdout)
        stderr = _decode_output(completed.stderr)
        if completed.returncode != 0:
            raise BossCliError(stderr.strip() or stdout.strip() or "Puppeteer 会话桥接失败")
        try:
            result = json.loads(stdout)
        except ValueError as exc:
            raise BossCliError("Puppeteer 会话桥接未返回有效 JSON") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise BossCliError("Puppeteer 会话桥接回执无效")
        return result

    def start_login(self, account):
        try:
            return subprocess.Popen(
                self._command(["login"]),
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._account_env(account),
            )
        except OSError as exc:
            raise BossCliError(f"boss-cli 无法启动：{exc}") from exc

    @staticmethod
    def stop_login(process):
        try:
            if process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    return
        except OSError:
            return

    def version(self):
        return self._run(["--version"], env=self._base_env(), timeout_seconds=20).stdout.strip()

    def login(self, account):
        return self._run(["login"], env=self._account_env(account), timeout_seconds=90)

    def positions(self, account):
        result = self._run(["positions"], env=self._account_env(account), timeout_seconds=180)
        return parse_positions(result.stdout)

    def _enrich_candidate_rows(self, account, source, rows):
        """Attach DOM stable IDs only when the CLI and browser snapshots align by index and name."""
        # boss-cli can return parsed text just before the search iframe finishes
        # replacing its candidate cards. Retry the read-only DOM snapshot briefly;
        # never accept a partial/empty ID set and never align by name alone.
        for attempt in range(4):
            try:
                response = self._run_chat_bridge(
                    account,
                    "candidate_list",
                    {"source": str(source)},
                    timeout_seconds=45,
                )
            except (BossCliError, BossCliTimeout):
                response = None
            browser_rows = response.get("rows") if isinstance(response, dict) else None
            if isinstance(browser_rows, list) and len(browser_rows) == len(rows):
                enriched = []
                seen_ids = set()
                aligned = True
                for parsed, observed in zip(rows, browser_rows):
                    parsed_name = str(parsed.get("display_name", "")).strip()
                    observed_name = str(observed.get("display_name", "")).strip()
                    external_id = str(observed.get("external_id", "")).strip()
                    if parsed_name != observed_name or not external_id or external_id in seen_ids:
                        aligned = False
                        break
                    seen_ids.add(external_id)
                    enriched.append({**parsed, "external_id": external_id})
                if aligned and len(enriched) == len(rows):
                    return enriched
            if attempt < 3:
                time.sleep(0.35 * (attempt + 1))
        return rows

    def recommend(self, account, job_keyword=""):
        keyword = str(job_keyword or "").strip()
        args = ["recommend", keyword] if keyword else ["recommend"]
        result = self._run(args, env=self._account_env(account), timeout_seconds=180)
        rows = parse_candidate_output(result.stdout, source="recommend")
        return self._enrich_candidate_rows(account, "recommend", rows)

    def search(self, account, keyword=""):
        keyword = str(keyword or "").strip()
        if len(keyword) > 20:
            raise BossCliError("常规搜索关键词最多 20 个字符")
        args = ["search", keyword] if keyword else ["search"]
        result = self._run(args, env=self._account_env(account), timeout_seconds=180)
        rows = parse_candidate_output(result.stdout, source="search")
        return self._enrich_candidate_rows(account, "search", rows)

    def deep_search(self, account, *, job="", core=None, bonus=None, match=False):
        values = [str(job or ""), *(core or []), *(bonus or [])]
        if any(len(str(value).strip()) > 200 for value in values):
            raise BossCliError("深度搜索单项条件最多 200 个字符")
        args = deep_search_args(job=job, core=core, bonus=bonus, match=match)
        result = self._run(args, env=self._account_env(account), timeout_seconds=240)
        if not match:
            return []
        rows = parse_candidate_output(result.stdout, source="deep_search")
        return self._enrich_candidate_rows(account, "deep_search", rows)

    def conversations(self, account, *, unread=False, job_title=""):
        job_name = str(job_title or "").strip()
        if len(job_name) > 120 or "\n" in job_name or "\r" in job_name:
            raise BossCliError("BOSS 沟通职位筛选值无效")
        result = self._run_chat_bridge(
            account,
            "list",
            {"job_title": job_name, "unread": bool(unread)},
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            raise BossCliError("Puppeteer 会话列表回执无效")
        lines = []
        for row in rows:
            parts = [
                f"{int(row['index'])}. {row['name']}",
                str(row.get("job_title", "")).strip(),
                f"external_id:{row['external_id']}",
            ]
            unread_count = int(row.get("unread_count", 0) or 0)
            if unread_count:
                parts.append(f"未读:{unread_count}")
            if row.get("selected"):
                parts.append("selected:1")
            preview = str(row.get("preview", "")).strip()
            if preview:
                parts.append(f"消息:{preview}")
            lines.append("｜".join(part for part in parts if part))
        return "\n".join(lines)

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

    def greet_by_external_id(
        self, account, external_id, *, message="", job_title="", source="recommend", expected_name=""
    ):
        normalized_id = str(external_id or "").strip()
        normalized_message = str(message or "").strip()
        if not normalized_id or len(normalized_id) > 160:
            raise BossCliError("候选人平台稳定 ID 无效")
        if not normalized_message or len(normalized_message) > 1000:
            raise BossCliError("统一打招呼话术必须为 1 到 1000 个字符")
        response = self._run_chat_bridge(
            account,
            "greet_candidate",
            {
                "external_id": normalized_id,
                "message": normalized_message,
                "job_title": str(job_title or ""),
                "source": str(source or "recommend"),
                "expected_name": str(expected_name or ""),
            },
            timeout_seconds=60,
        )
        receipt = response.get("receipt") if isinstance(response, dict) else None
        if (
            not isinstance(receipt, dict)
            or receipt.get("verified") is not True
            or receipt.get("greeting_verified") is not True
            or str(receipt.get("observed_external_id", "")).strip() != normalized_id
        ):
            raise BossCliError("未能确认已向稳定 ID 对应的候选人打招呼")
        return receipt

    def preview_by_external_id(self, account, external_id):
        normalized_id = str(external_id or "").strip()
        if not normalized_id or len(normalized_id) > 160:
            raise BossCliError("候选人平台稳定 ID 无效")
        response = self._run_chat_bridge(
            account,
            "preview_candidate",
            {"external_id": normalized_id},
            timeout_seconds=90,
        )
        receipt = response.get("receipt") if isinstance(response, dict) else None
        output = str(response.get("output", "")) if isinstance(response, dict) else ""
        if (
            not isinstance(receipt, dict)
            or receipt.get("verified") is not True
            or str(receipt.get("observed_external_id", "")).strip() != normalized_id
            or not output.strip()
        ):
            raise BossCliError("未能确认稳定 ID 对应候选人的在线简历预览")
        return CliResult(returncode=0, stdout=output, stderr="")

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

    def _assert_selected_conversation(self, account, external_id, *, job_title=""):
        result = self._run_chat_bridge(
            account,
            "selected",
            {"external_id": str(external_id), "job_title": str(job_title)},
        )
        selected = result.get("conversation")
        if not isinstance(selected, dict):
            raise BossCliError("Puppeteer 当前会话回执无效")
        if str(selected.get("external_id", "")).strip() != str(external_id).strip():
            raise BossCliError("打开后的 BOSS 会话稳定 ID 与批准目标不一致")
        expected_job = str(job_title or "").strip()
        if expected_job and str(selected.get("job_title", "")).strip() != expected_job:
            raise BossCliError("打开后的 BOSS 会话职位与批准目标不一致")
        return selected

    def open_chat_by_external_id(self, account, external_id, *, job_title="", unread=False):
        normalized = str(external_id or "").strip()
        if not normalized or len(normalized) > 160:
            raise BossCliError("候选人平台稳定 ID 无效")
        result = self._run_chat_bridge(
            account,
            "open",
            {
                "external_id": normalized,
                "job_title": str(job_title),
                "unread": bool(unread),
            },
        )
        snapshot = result.get("conversation")
        if not isinstance(snapshot, dict):
            raise BossCliError("Puppeteer 打开会话回执无效")
        role = {"candidate": "candidate", "hr": "you", "system": "system"}
        lines = [f"成功进入候选人聊天：{snapshot['name']}", "", "完整聊天消息："]
        for message in snapshot.get("messages", []):
            tag = role.get(str(message.get("direction", "")))
            content = str(message.get("content", "")).strip()
            if tag and content:
                lines.append(f"[{tag}] {content}")
        return CliResult(returncode=0, stdout="\n".join(lines), stderr="")

    def request_resume_by_external_id(
        self, account, external_id, *, message="", first_contact=False, job_title=""
    ):
        opened = self.open_chat_by_external_id(account, external_id, job_title=job_title)
        self._assert_selected_conversation(account, external_id, job_title=job_title)
        normalized = str(message or "").strip()
        previous_count = 0
        if first_contact:
            from recruitment.rpa.conversations import parse_chat_messages

            if not normalized or len(normalized) > 1000 or "\n" in normalized or "\r" in normalized:
                raise BossCliError("首次联系求简历必须提供 1 到 1000 个字符的单行话术")
            previous_count = sum(
                1 for item in parse_chat_messages(opened.stdout)
                if item.get("direction") == "hr"
                and " ".join(str(item.get("content", "")).split()).strip() == normalized
            )
        response = self._run_chat_bridge(
            account,
            "request_resume",
            {
                "external_id": str(external_id),
                "job_title": str(job_title),
                "message": normalized,
                "previous_count": previous_count,
                "first_contact": bool(first_contact),
            },
        )
        receipt = response.get("receipt") if isinstance(response, dict) else None
        if (
            not isinstance(receipt, dict)
            or receipt.get("verified") is not True
            or receipt.get("greeting_verified") is not True
            or receipt.get("resume_requested") is not True
            or receipt.get("request_acknowledged") is not True
            or str(receipt.get("observed_external_id", "")) != str(external_id)
        ):
            raise BossCliError("未能确认已向目标候选人打招呼并发出求简历请求")
        return receipt

    def send_text_by_external_id(self, account, external_id, message, *, job_title=""):
        from recruitment.rpa.conversations import parse_chat_messages

        normalized = str(message or "").strip()
        if not normalized or len(normalized) > 1000 or "\n" in normalized or "\r" in normalized:
            raise BossCliError("发送内容必须为 1 到 1000 个字符的单行文本")
        opened = self.open_chat_by_external_id(account, external_id, job_title=job_title)
        self._assert_selected_conversation(account, external_id, job_title=job_title)
        previous_count = sum(
            1 for item in parse_chat_messages(opened.stdout)
            if item.get("direction") == "hr"
            and " ".join(str(item.get("content", "")).split()).strip() == normalized
        )
        response = self._run_chat_bridge(
            account,
            "send_text",
            {
                "external_id": str(external_id),
                "job_title": str(job_title),
                "message": normalized,
                "previous_count": previous_count,
            },
        )
        confirmed = response.get("receipt") if isinstance(response, dict) else None
        if (
            not isinstance(confirmed, dict)
            or confirmed.get("verified") is not True
            or str(confirmed.get("external_id", "")) != str(external_id)
        ):
            raise BossCliError("发送后未确认聊天区出现新的己方消息")
        return {
            "sent": True,
            "verified": True,
            "expected_external_id": str(external_id),
            "observed_external_id": str(confirmed.get("external_id", "")),
        }

    def download_resume_attachments(
        self, account, external_id, expected_name, output_dir, *, job_title=""
    ):
        result = self._run_chat_bridge(
            account,
            "download_attachments",
            {
                "external_id": str(external_id),
                "expected_name": str(expected_name),
                "job_title": str(job_title),
                "output_dir": str(Path(output_dir).resolve()),
            },
            timeout_seconds=120,
        )
        attachments = result.get("attachments")
        if not isinstance(attachments, list):
            raise BossCliError("Puppeteer 简历附件回执无效")
        return attachments

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
