from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

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
