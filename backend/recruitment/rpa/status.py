import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class BossBrowserStatus:
    login_status: str
    verification_status: str = ""
    detail: str = ""


def classify_boss_pages(pages):
    combined = " ".join(f"{page.get('url', '')} {page.get('title', '')}" for page in pages).lower()
    if "token 无效" in combined or "token invalid" in combined or "二维码已失效" in combined:
        return BossBrowserStatus("waiting_human", "token_invalid", "登录二维码已失效")
    if any(marker in combined for marker in ("security-check", "安全验证", "captcha", "verify")):
        return BossBrowserStatus("waiting_human", "risk_control", "需要人工完成安全验证")
    if any(marker in combined for marker in ("header-login", "登录boss直聘", "/web/user/")):
        return BossBrowserStatus("waiting_login", "", "等待人工登录")
    if "zhipin.com" in combined:
        return BossBrowserStatus("ready", "", "BOSS 账号已登录")
    return BossBrowserStatus("waiting_login", "", "未检测到已登录的 BOSS 页面")


def inspect_boss_status(port, *, timeout=1):
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/json/list", timeout=timeout) as response:
            pages = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return BossBrowserStatus("browser_stopped", "", "隔离浏览器未启动")
    return classify_boss_pages(pages)

