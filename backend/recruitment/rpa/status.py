import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from recruitment.rpa.browser import cdp_is_running, managed_cdp_matches


@dataclass(frozen=True)
class BossBrowserStatus:
    login_status: str
    verification_status: str = ""
    detail: str = ""
    target_page_ready: bool = False


_AUTHENTICATED_RECRUITER_PATHS = (
    "/web/chat/",
    "/web/geek/resume",
)


def _is_authenticated_recruiter_page(raw_url):
    try:
        parsed = urlsplit(str(raw_url or ""))
    except ValueError:
        return False
    path = parsed.path.lower()
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "www.zhipin.com"
        and any(path.startswith(prefix) for prefix in _AUTHENTICATED_RECRUITER_PATHS)
    )


def classify_boss_pages(pages):
    page_rows = [page for page in pages if isinstance(page, dict)] if isinstance(pages, list) else []
    combined = " ".join(f"{page.get('url', '')} {page.get('title', '')}" for page in page_rows).lower()
    if "token 无效" in combined or "token invalid" in combined or "二维码已失效" in combined:
        return BossBrowserStatus("waiting_human", "token_invalid", "登录二维码已失效", True)
    if any(marker in combined for marker in ("security-check", "安全验证", "captcha", "verify")):
        return BossBrowserStatus("waiting_human", "risk_control", "需要人工完成安全验证", True)
    if any(marker in combined for marker in ("header-login", "登录boss直聘", "/web/user/")):
        return BossBrowserStatus("waiting_login", "", "等待人工登录", True)
    if any(marker in combined for marker in ("/web/common/error", "页面出错", "page error")):
        return BossBrowserStatus("error", "", "BOSS 页面状态异常", True)
    if any(_is_authenticated_recruiter_page(page.get("url")) for page in page_rows):
        return BossBrowserStatus("ready", "", "BOSS 账号已登录", True)
    return BossBrowserStatus("waiting_login", "", "未检测到已登录的 BOSS 页面")


def inspect_boss_status(port, *, user_data_dir=None, timeout=1):
    if user_data_dir and cdp_is_running(port, timeout=min(timeout, 0.5)):
        if not managed_cdp_matches(port, user_data_dir):
            return BossBrowserStatus("error", "cdp_identity_mismatch", "调试端口不属于该账号的隔离浏览器")
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/json/list", timeout=timeout) as response:
            pages = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return BossBrowserStatus("browser_stopped", "", "隔离浏览器未启动")
    return classify_boss_pages(pages)
