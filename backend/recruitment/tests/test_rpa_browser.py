from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount
from recruitment.rpa.browser import (
    ProfileLock,
    ProfileLockedError,
    browser_configuration,
)


@override_settings(RPA_PROFILE_ROOT=Path("C:/hr-test/profiles"))
class BrowserConfigurationTests(SimpleTestCase):
    def test_edge_uses_trusted_executable_and_derived_profile(self):
        config = browser_configuration("edge", "boss-account-a", 53471, exists=lambda path: True)

        self.assertTrue(str(config.executable).lower().endswith("microsoft\\edge\\application\\msedge.exe"))
        self.assertEqual(config.user_data_dir, Path("C:/hr-test/profiles/boss-account-a"))
        self.assertEqual(config.port, 53471)

    def test_profile_slug_cannot_escape_root(self):
        with self.assertRaisesMessage(ValueError, "浏览器目录标识无效"):
            browser_configuration("chrome", "../default", 53470, exists=lambda path: True)

    def test_unknown_browser_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "不支持的浏览器"):
            browser_configuration("firefox", "boss-account-a", 53470, exists=lambda path: True)

    def test_second_profile_lock_is_rejected(self):
        profile = Path(settings.RPA_PROFILE_ROOT) / "boss-account-a"
        with ProfileLock(profile):
            with self.assertRaisesMessage(ProfileLockedError, "浏览器目录正在使用"):
                with ProfileLock(profile):
                    pass


class BossAccountConfigurationApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="browser-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.client.force_login(self.hr)

    @override_settings(RPA_PROFILE_ROOT=Path("C:/hr-test/profiles"))
    def test_account_configuration_is_derived_by_server(self):
        response = self.client.post(
            "/api/recruitment/boss-accounts/",
            {
                "name": "边缘浏览器账号",
                "browser_type": "edge",
                "browser_profile": "../../injected",
                "browser_executable": "C:/malware.exe",
                "user_data_dir": "C:/shared-profile",
                "cdp_port": 1,
                "daily_contact_limit": 30,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        account = BossAccount.objects.get(pk=response.data["id"])
        self.assertTrue(account.browser_profile.startswith("boss-"))
        self.assertNotEqual(account.browser_profile, "../../injected")
        self.assertNotEqual(account.browser_executable, "C:/malware.exe")
        self.assertEqual(account.user_data_dir, str(Path("C:/hr-test/profiles") / account.browser_profile))
        self.assertGreaterEqual(account.cdp_port, 53470)
        self.assertTrue(account.authorized_users.filter(pk=self.hr.pk).exists())
