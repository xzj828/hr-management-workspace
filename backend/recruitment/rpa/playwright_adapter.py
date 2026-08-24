from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


class BrowserConnectionError(RuntimeError):
    pass


class BrowserInventory:
    MIN_PORT = 53470
    MAX_PORT = 53569

    def __init__(self, port):
        self.port = int(port)
        if not self.MIN_PORT <= self.port <= self.MAX_PORT:
            raise ValueError("浏览器调试端口不在系统管理范围内")

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.port}"

    def pages(self):
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.endpoint)
                return [
                    {"url": page.url, "title": page.title()}
                    for context in browser.contexts
                    for page in context.pages
                ]
        except PlaywrightError as exc:
            raise BrowserConnectionError(f"无法连接隔离浏览器：{exc}") from exc
