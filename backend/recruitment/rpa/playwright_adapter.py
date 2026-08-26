import hashlib
from pathlib import Path
import re
import uuid

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

    def positions(self):
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.endpoint)
                pages = [
                    page for context in browser.contexts for page in context.pages
                    if str(page.url).startswith("https://www.zhipin.com/")
                ]
                if not pages:
                    raise BrowserConnectionError("未找到已登录的 BOSS 页面")
                page = pages[-1]
                if not str(page.url).startswith("https://www.zhipin.com/web/chat/job/list"):
                    page.goto(
                        "https://www.zhipin.com/web/chat/job/list",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                selector = ".job-item-container, .job-jobInfo-warp"
                cards = None
                for attempt in range(3):
                    frame = next((item for item in page.frames if "/web/frame/job_v2/list" in str(item.url)), None)
                    if frame is None:
                        page.wait_for_selector('iframe[src*="/web/frame/job_v2/list"]', timeout=15_000)
                        frame = next((item for item in page.frames if "/web/frame/job_v2/list" in str(item.url)), None)
                    if frame is None:
                        raise BrowserConnectionError("未找到 BOSS 职位列表")
                    try:
                        frame.wait_for_function(
                            """selector => document.querySelectorAll(selector).length > 0
                            || /共\\s*0\\s*个职位/.test(document.body?.innerText || '')""",
                            arg=selector,
                            timeout=15_000,
                        )
                        cards = frame.eval_on_selector_all(
                            selector,
                            """rows => rows.map((el) => ({
                              id: (el.getAttribute('data-id') || '').trim(),
                              title: (el.querySelector('.job-name, .job-title a')?.textContent || '').replace(/\\s+/g, ' ').trim(),
                              status: (el.querySelector('.job-status-wrapper .status-box')?.textContent || '').replace(/\\s+/g, ' ').trim(),
                              meta: Array.from(el.querySelectorAll('.info-labels .divider-label-text, .job-main-info-wrapper .info-labels span'))
                                .map((item) => (item.textContent || '').replace(/\\s+/g, ' ').trim())
                                .filter(Boolean),
                            })).filter((row) => row.title)""",
                        )
                        break
                    except PlaywrightError as exc:
                        if "Execution context was destroyed" not in str(exc) or attempt == 2:
                            raise
                        page.wait_for_timeout(300)
                positions = []
                for card in cards or []:
                    title = str(card.get("title", "")).strip()
                    status_text = str(card.get("status", "")).strip()
                    meta = [str(value).strip() for value in card.get("meta", []) if str(value).strip()]
                    external_id = str(card.get("id", "")).strip()
                    if not external_id:
                        identity = "｜".join([title, *meta])
                        external_id = f"derived-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
                    status = "open" if "开放中" in status_text else "closed" if "已关闭" in status_text else "paused"
                    positions.append({
                        "external_id": external_id,
                        "title": title,
                        "status": status,
                        "raw": "｜".join([title, f"状态:{status_text}", *meta]),
                    })
                return positions
        except BrowserConnectionError:
            raise
        except PlaywrightError as exc:
            raise BrowserConnectionError(f"无法读取 BOSS 职位列表：{exc}") from exc

    @staticmethod
    def _conversation_job_title(value):
        return re.split(r"\s+_\s+", " ".join(str(value or "").split()), maxsplit=1)[0].strip()

    def _select_conversation_scope(self, page, *, job_title, unread):
        expected_job = self._conversation_job_title(job_title)
        if not expected_job or len(expected_job) > 120:
            raise BrowserConnectionError("BOSS 沟通职位筛选值无效")

        label = page.locator(".chat-top-job .chat-select-job")
        if label.count() != 1:
            raise BrowserConnectionError("未找到 BOSS 沟通职位筛选器")
        current_job = self._conversation_job_title(label.inner_text())
        if current_job != expected_job:
            label.click()
            page.wait_for_function(
                "() => document.querySelectorAll('.chat-top-job .ui-dropmenu-list li').length > 0",
                timeout=10_000,
            )
            options = page.locator(".chat-top-job .ui-dropmenu-list li")
            matches = [
                options.nth(index)
                for index in range(options.count())
                if self._conversation_job_title(options.nth(index).inner_text()) == expected_job
            ]
            if len(matches) != 1:
                raise BrowserConnectionError("BOSS 沟通职位无法精确唯一匹配")
            matches[0].click()
            page.wait_for_function(
                r"""expected => {
                  const norm = value => (value || '').replace(/\s+/g, ' ').trim();
                  const title = norm(document.querySelector('.chat-top-job .chat-select-job')?.textContent)
                    .split(/\s+_\s+/, 1)[0].trim();
                  return title === expected;
                }""",
                arg=expected_job,
                timeout=15_000,
            )

        filter_label = "未读" if unread else "全部"
        tabs = page.locator(".chat-message-filter-left span")
        matches = [
            tabs.nth(index)
            for index in range(tabs.count())
            if " ".join(tabs.nth(index).inner_text().split()) == filter_label
        ]
        if len(matches) != 1:
            raise BrowserConnectionError(f"未找到 BOSS 沟通“{filter_label}”筛选")
        selected_class = str(matches[0].get_attribute("class") or "").split()
        if not ({"active", "selected", "current", "checked"} & set(selected_class)):
            matches[0].click()
        # BOSS updates the label before its conversation request settles.  A
        # short floor prevents accepting the previous job's rows as an empty
        # result while still allowing a legitimate zero-unread scope.
        page.wait_for_timeout(750)
        page.wait_for_function(
            r"""scope => {
              const norm = value => (value || '').replace(/\s+/g, ' ').trim();
              const tabs = Array.from(document.querySelectorAll('.chat-message-filter-left span'));
              const tab = tabs.find(item => norm(item.textContent) === scope.filter);
              if (!tab || !/(active|selected|current|checked)/.test(String(tab.className || ''))) return false;
              const rows = Array.from(document.querySelectorAll('.geek-item'));
              if (!rows.length) {
                const key = `${scope.job}:${scope.filter}`;
                const now = Date.now();
                const previous = window.__ximingConversationEmptyScope;
                if (previous?.key === key && now - previous.since >= 1000) return true;
                window.__ximingConversationEmptyScope = { key, since: now };
                return false;
              }
              window.__ximingConversationEmptyScope = null;
              return rows.every(row => {
                const job = norm(row.querySelector('.source-job')?.textContent);
                const badge = norm(row.querySelector('.badge-count')?.textContent).replace(/\D/g, '');
                return job === scope.job && (!scope.unread || Number.parseInt(badge || '0', 10) > 0);
              });
            }""",
            arg={"job": expected_job, "filter": filter_label, "unread": bool(unread)},
            timeout=18_000,
        )

    def conversation_rows(self, *, job_title="", unread=None):
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.endpoint)
                pages = [
                    page for context in browser.contexts for page in context.pages
                    if str(page.url).startswith("https://www.zhipin.com/")
                ]
                if not pages:
                    raise BrowserConnectionError("未找到已登录的 BOSS 页面")
                page = pages[-1]
                if not str(page.url).startswith("https://www.zhipin.com/web/chat/index"):
                    raise BrowserConnectionError("当前不在 BOSS 沟通列表页")
                if str(job_title or "").strip():
                    self._select_conversation_scope(page, job_title=job_title, unread=bool(unread))
                rows = page.locator(".geek-item").evaluate_all(
                    r"""items => items.map((el, index) => {
                      const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
                      const badge = norm(el.querySelector('.badge-count')?.textContent);
                      const digits = badge.replace(/\D/g, '');
                      return {
                        index: index + 1,
                        external_id: norm(el.getAttribute('data-id')),
                        name: norm(el.querySelector('.geek-name')?.textContent),
                        job_title: norm(el.querySelector('.source-job')?.textContent),
                        preview: norm(el.querySelector('.push-text')?.textContent),
                        unread_count: digits ? (parseInt(digits, 10) || 0) : 0,
                        selected: el.classList.contains('selected'),
                      };
                    }).filter((row) => row.external_id && row.name)""",
                )
                external_ids = [str(row.get("external_id", "")).strip() for row in rows]
                if len(external_ids) != len(set(external_ids)):
                    raise BrowserConnectionError("BOSS 沟通列表存在重复稳定 ID")
                return rows
        except BrowserConnectionError:
            raise
        except PlaywrightError as exc:
            raise BrowserConnectionError(f"无法读取 BOSS 沟通列表：{exc}") from exc

    def selected_conversation(self):
        selected = [row for row in self.conversation_rows() if row.get("selected")]
        if len(selected) != 1:
            raise BrowserConnectionError("无法唯一确认当前 BOSS 沟通会话")
        return selected[0]

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

    def download_resume_attachments(self, expected_name, output_dir):
        normalized = str(expected_name or "").strip()
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        downloaded = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.endpoint)
                pages = [page for context in browser.contexts for page in context.pages if str(page.url).startswith("https://www.zhipin.com/")]
                if not pages:
                    raise BrowserConnectionError("未找到 BOSS 沟通页面")
                page = pages[-1]
                selected = page.locator(".geek-item.selected .geek-name")
                if selected.count() != 1 or " ".join(selected.inner_text().split()).strip() != normalized:
                    raise BrowserConnectionError("沟通会话身份核验失败，已禁止读取附件")
                icons = page.locator(".chat-message-list:visible .message-item .item-friend .resume-icon")
                for index in range(min(icons.count(), 10)):
                    item = icons.nth(index).locator("xpath=ancestor::div[contains(@class,'message-item')]")
                    button = item.locator(".message-card-buttons .card-btn")
                    if button.count() != 1:
                        continue
                    try:
                        with page.expect_download(timeout=5000) as info:
                            button.click()
                        download = info.value
                        filename = Path(download.suggested_filename or f"{normalized}-附件简历.pdf").name
                        if not filename.lower().endswith(".pdf"):
                            continue
                        target = directory / f"attachment-{uuid.uuid4().hex}.pdf"
                        download.save_as(str(target))
                        downloaded.append({"path": str(target), "filename": filename})
                    except PlaywrightError:
                        continue
                return downloaded
        except BrowserConnectionError:
            raise
        except PlaywrightError as exc:
            raise BrowserConnectionError(f"简历附件读取失败：{exc}") from exc
