from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from playwright.sync_api import Error as PlaywrightError

from recruitment.rpa.playwright_adapter import BrowserInventory


class PlaywrightAdapterTests(SimpleTestCase):
    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_inventory_connects_to_loopback_cdp_only(self, sync_playwright):
        page = MagicMock()
        page.url = "https://www.zhipin.com/web/chat/job/list"
        page.title.return_value = "职位管理"
        browser = MagicMock()
        browser.contexts = [MagicMock(pages=[page])]
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser

        rows = BrowserInventory(53470).pages()

        self.assertEqual(rows, [{"url": page.url, "title": "职位管理"}])
        playwright.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:53470")
        browser.close.assert_not_called()
        sync_playwright.return_value.__exit__.assert_called_once()

    def test_inventory_rejects_a_port_outside_the_managed_range(self):
        with self.assertRaises(ValueError):
            BrowserInventory(9222)

    def test_conversation_job_option_uses_exact_title_before_location_and_salary(self):
        self.assertEqual(
            BrowserInventory._conversation_job_title("前置部署工程师 _ 北京 3-6K"),
            "前置部署工程师",
        )
        self.assertNotEqual(
            BrowserInventory._conversation_job_title("FDE（前置部署工程师）（关闭） _ 北京 3-6K"),
            "前置部署工程师",
        )

    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_positions_reads_current_job_card_structure(self, sync_playwright):
        frame = MagicMock()
        frame.url = "https://www.zhipin.com/web/frame/job_v2/list?jobversion=11173"
        cards = [{
            "id": "",
            "title": "前置部署工程师",
            "status": "开放中",
            "meta": ["北京", "本科", "3-6K"],
        }]
        frame.eval_on_selector_all.side_effect = [
            PlaywrightError("Execution context was destroyed"),
            cards,
        ]
        page = MagicMock()
        page.url = "https://www.zhipin.com/web/chat/job/list"
        page.frames = [MagicMock(url=page.url), frame]
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser

        rows = BrowserInventory(53470).positions()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "前置部署工程师")
        self.assertEqual(rows[0]["status"], "open")
        self.assertTrue(rows[0]["external_id"].startswith("derived-"))
        self.assertIn("arg", frame.wait_for_function.call_args.kwargs)
        self.assertEqual(frame.eval_on_selector_all.call_count, 2)

    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_conversation_rows_require_unique_platform_ids(self, sync_playwright):
        page = MagicMock()
        page.url = "https://www.zhipin.com/web/chat/index"
        page.eval_on_selector_all.return_value = [
            {
                "index": 1,
                "external_id": "conversation-101",
                "name": "林然",
                "job_title": "产品经理",
                "preview": "你好",
                "unread_count": 1,
                "selected": True,
            }
        ]
        page.locator.return_value.evaluate_all.return_value = page.eval_on_selector_all.return_value
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser

        rows = BrowserInventory(53470).conversation_rows()

        self.assertEqual(rows[0]["external_id"], "conversation-101")
        self.assertEqual(BrowserInventory(53470).selected_conversation()["name"], "林然")

    @patch.object(BrowserInventory, "_select_conversation_scope")
    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_conversation_rows_applies_job_before_reading_scoped_rows(self, sync_playwright, select_scope):
        page = MagicMock()
        page.url = "https://www.zhipin.com/web/chat/index"
        page.locator.return_value.evaluate_all.return_value = [{
            "index": 1,
            "external_id": "conversation-job-1",
            "name": "耿柔",
            "job_title": "前置部署工程师",
            "preview": "您好",
            "unread_count": 1,
            "selected": False,
        }]
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser

        rows = BrowserInventory(53470).conversation_rows(job_title="前置部署工程师", unread=True)

        select_scope.assert_called_once_with(
            page,
            job_title="前置部署工程师",
            unread=True,
        )
        self.assertEqual(rows[0]["external_id"], "conversation-job-1")

    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_conversation_rows_reject_duplicate_platform_ids(self, sync_playwright):
        page = MagicMock()
        page.url = "https://www.zhipin.com/web/chat/index"
        page.eval_on_selector_all.return_value = [
            {"external_id": "duplicate", "name": "林然", "selected": False},
            {"external_id": "duplicate", "name": "周青", "selected": False},
        ]
        page.locator.return_value.evaluate_all.return_value = page.eval_on_selector_all.return_value
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser

        with self.assertRaisesMessage(RuntimeError, "重复稳定 ID"):
            BrowserInventory(53470).conversation_rows()

    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_open_conversation_scopes_before_clicking_stable_id(self, sync_playwright):
        page = MagicMock()
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser
        inventory = BrowserInventory(53470)
        events = []
        target = {
            "index": 2,
            "external_id": "conversation-101",
            "name": "林然",
            "job_title": "测试工程师",
            "unread_count": 1,
            "selected": False,
        }
        row_locator = MagicMock()
        row_locator.nth.return_value.click.side_effect = lambda: events.append("click")
        page.locator.return_value = row_locator

        with patch.object(inventory, "_conversation_page", return_value=page), patch.object(
            inventory,
            "_select_conversation_scope",
            side_effect=lambda *args, **kwargs: events.append("scope"),
        ) as select_scope, patch.object(
            inventory,
            "_conversation_rows",
            side_effect=lambda *args, **kwargs: events.append("rows") or [target],
        ), patch.object(
            inventory,
            "_current_conversation_messages",
            side_effect=lambda *args, **kwargs: events.append("messages") or [],
        ):
            opened = inventory.open_conversation(
                "conversation-101",
                job_title="测试工程师",
                unread=True,
            )

        self.assertEqual(events, ["scope", "rows", "click", "messages"])
        select_scope.assert_called_once_with(
            page,
            job_title="测试工程师",
            unread=True,
        )
        row_locator.nth.assert_called_once_with(1)
        self.assertTrue(opened["selected"])
        self.assertEqual(opened["external_id"], "conversation-101")

    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_wait_for_outgoing_message_requires_new_exact_message_on_selected_chat(self, sync_playwright):
        page = MagicMock()
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser
        inventory = BrowserInventory(53470)

        with patch.object(inventory, "_conversation_page", return_value=page):
            inventory.wait_for_outgoing_message(
                "conversation-101",
                "您好，方便发送一份简历吗？",
                previous_count=1,
                job_title="测试工程师",
            )

        arguments = page.wait_for_function.call_args.kwargs["arg"]
        self.assertEqual(arguments["externalId"], "conversation-101")
        self.assertEqual(arguments["jobTitle"], "测试工程师")
        self.assertEqual(arguments["message"], "您好，方便发送一份简历吗？")
        self.assertEqual(arguments["previousCount"], 1)

    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_pdf_export_requires_expected_candidate_on_boss_page(self, sync_playwright):
        page = MagicMock()
        page.url = "https://www.zhipin.com/web/geek/resume"
        page.locator.return_value.count.return_value = 1
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        playwright = sync_playwright.return_value.__enter__.return_value
        playwright.chromium.connect_over_cdp.return_value = browser

        BrowserInventory(53470).save_pdf("林然", "resume.pdf")

        page.locator.assert_called_with("text=林然")
        page.pdf.assert_called_once()
        browser.close.assert_not_called()
