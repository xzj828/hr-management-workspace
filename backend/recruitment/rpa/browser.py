import os
import re
import socket
import threading
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from django.conf import settings


class BrowserUnavailableError(RuntimeError):
    pass


class ProfileLockedError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserConfiguration:
    browser_type: str
    executable: Path
    user_data_dir: Path
    port: int


BROWSER_CANDIDATES = {
    "chrome": (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ),
    "edge": (
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ),
}

_PROFILE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_locked_profiles: set[Path] = set()
_locked_profiles_guard = threading.Lock()
_MANAGED_CDP_MARKER = ".ximing-managed-cdp.json"


def browser_configuration(browser_type, profile_slug, port, *, exists=None):
    if browser_type not in BROWSER_CANDIDATES:
        raise ValueError("不支持的浏览器")
    if not _PROFILE_SLUG.fullmatch(profile_slug or ""):
        raise ValueError("浏览器目录标识无效")

    profile_root = Path(settings.RPA_PROFILE_ROOT).resolve()
    user_data_dir = (profile_root / profile_slug).resolve()
    if not user_data_dir.is_relative_to(profile_root):
        raise ValueError("浏览器目录标识无效")

    path_exists = exists or Path.exists
    executable = next((path for path in BROWSER_CANDIDATES[browser_type] if path_exists(path)), None)
    if executable is None:
        raise BrowserUnavailableError(f"未找到 {browser_type} 浏览器")

    return BrowserConfiguration(browser_type, executable.resolve(), user_data_dir, int(port))


def cdp_is_running(port, *, timeout=0.3):
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _managed_profile_dir(user_data_dir):
    profile_root = Path(settings.RPA_PROFILE_ROOT).resolve()
    profile_dir = Path(user_data_dir).resolve()
    if not profile_dir.is_relative_to(profile_root):
        raise BrowserUnavailableError("隔离浏览器目录不在受管范围内")
    return profile_dir


def read_cdp_identity(port, *, timeout=0.5):
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None
    websocket_url = str(payload.get("webSocketDebuggerUrl", "")).strip()
    if not websocket_url:
        return None
    return {
        "port": int(port),
        "websocket_url": websocket_url,
        "browser": str(payload.get("Browser", ""))[:200],
    }


def record_managed_cdp(port, user_data_dir):
    identity = read_cdp_identity(port)
    if identity is None:
        raise BrowserUnavailableError("隔离浏览器调试端口尚未就绪")
    profile_dir = _managed_profile_dir(user_data_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    marker = profile_dir / _MANAGED_CDP_MARKER
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(identity, ensure_ascii=True), encoding="utf-8")
    temporary.replace(marker)
    return identity


def managed_cdp_matches(port, user_data_dir):
    identity = read_cdp_identity(port)
    if identity is None:
        return False
    try:
        marker = _managed_profile_dir(user_data_dir) / _MANAGED_CDP_MARKER
        expected = json.loads(marker.read_text(encoding="utf-8"))
    except (BrowserUnavailableError, OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        expected.get("port") == identity["port"]
        and expected.get("websocket_url") == identity["websocket_url"]
    )


def port_is_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
    return True


class ProfileLock:
    def __init__(self, profile_dir):
        self.profile_dir = Path(profile_dir).resolve()
        self._file = None
        self._process_guarded = False

    def __enter__(self):
        with _locked_profiles_guard:
            if self.profile_dir in _locked_profiles:
                raise ProfileLockedError("浏览器目录正在使用")
            _locked_profiles.add(self.profile_dir)
            self._process_guarded = True

        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._file = (self.profile_dir / ".worker.lock").open("a+b")
            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"\0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
        except (OSError, IOError):
            self._release()
            raise ProfileLockedError("浏览器目录正在使用") from None
        return self

    def _release(self):
        if self._file is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._file.close()
            self._file = None
        if self._process_guarded:
            with _locked_profiles_guard:
                _locked_profiles.discard(self.profile_dir)
            self._process_guarded = False

    def __exit__(self, exc_type, exc_value, traceback):
        self._release()
