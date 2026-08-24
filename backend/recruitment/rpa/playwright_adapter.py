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

    def save_pdf(self, expected_name, output_path):
        normalized = str(expected_name or "").strip()
        if not normalized:
            raise BrowserConnectionError("缺少候选人身份，禁止保存在线简历")
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.endpoint)
                pages = [
                    page for context in browser.contexts for page in context.pages
                    if str(page.url).startswith("https://www.zhipin.com/")
                ]
                if not pages:
                    raise BrowserConnectionError("未找到 BOSS 在线简历页面")
                page = pages[-1]
                if page.locator(f"text={normalized}").count() != 1:
                    raise BrowserConnectionError("在线简历身份核验失败，已禁止保存")
                page.pdf(path=str(output_path), format="A4", print_background=True)
                return str(output_path)
        except BrowserConnectionError:
            raise
        except PlaywrightError as exc:
            raise BrowserConnectionError(f"在线简历 PDF 保存失败：{exc}") from exc
