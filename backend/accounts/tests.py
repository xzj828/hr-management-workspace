import json
import socket
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from .crypto import encrypt_secret
from .models import UserModelCredential, UserModelProfile


PUBLIC_IPV4 = "93.184.216.34"


class GatewayNetworkMixin:
    def configure_gateway_network(self):
        cache.clear()
        getaddrinfo_patcher = patch("accounts.services.model_endpoint.socket.getaddrinfo")
        https_connection_patcher = patch("accounts.services.model_gateway.HTTPSConnection")
        self.mock_getaddrinfo = getaddrinfo_patcher.start()
        self.mock_https_connection_class = https_connection_patcher.start()
        self.addCleanup(getaddrinfo_patcher.stop)
        self.addCleanup(https_connection_patcher.stop)
        self.mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_IPV4, 443))
        ]
        self.https_connection = self.mock_https_connection_class.return_value
        self.https_connection.sock.getpeername.return_value = (PUBLIC_IPV4, 443)


class PinnedConnectionProbe:
    def __init__(self, host, port, *, timeout, **_kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.request = MagicMock()
        self.getresponse = MagicMock()

    def connect(self):
        self.sock = self._create_connection((self.host, self.port), self.timeout, None)

    def close(self):
        if self.sock is not None:
            self.sock.close()


class ModelCredentialApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="hr-model", password="strong-password-123")
        self.client.force_login(self.user)

    def test_saves_key_encrypted_and_returns_only_last_four(self):
        response = self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": "sk-secret-1234"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        credential = UserModelCredential.objects.get(user=self.user)
        self.assertNotIn("sk-secret-1234", credential.encrypted_api_key)
        self.assertEqual(response.data["key_last4"], "1234")
        self.assertNotIn("api_key", response.data)
        profile = UserModelProfile.objects.get(user=self.user, is_active=True)
        self.assertEqual(profile.encrypted_api_key, credential.encrypted_api_key)
        self.assertEqual(profile.model, credential.model)

    def test_saved_key_is_available_after_a_new_login(self):
        self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": "sk-secret-5678"},
            format="json",
        )
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get("/api/account/model-credential/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["has_api_key"])
        self.assertEqual(response.data["key_last4"], "5678")

    def test_user_cannot_read_another_users_configuration(self):
        other = User.objects.create_user(username="other", password="strong-password-123")
        UserModelCredential.objects.create(user=other, api_url="https://other.example/v1", model="other")
        response = self.client.get("/api/account/model-credential/")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["api_url"], "https://other.example/v1")

    def test_legacy_put_cannot_clear_api_url(self):
        self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": "sk-secret-1234"},
            format="json",
        )

        response = self.client.put("/api/account/model-credential/", {"api_url": ""}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_url", response.data)
        credential = UserModelCredential.objects.get(user=self.user)
        active = UserModelProfile.objects.get(user=self.user, is_active=True)
        self.assertEqual(credential.api_url, "https://models.example/v1")
        self.assertEqual(active.api_url, credential.api_url)

    def test_legacy_put_cannot_clear_model(self):
        self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": "sk-secret-1234"},
            format="json",
        )

        response = self.client.put("/api/account/model-credential/", {"model": ""}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("model", response.data)
        credential = UserModelCredential.objects.get(user=self.user)
        active = UserModelProfile.objects.get(user=self.user, is_active=True)
        self.assertEqual(credential.model, "example-chat")
        self.assertEqual(active.model, credential.model)

    def test_legacy_put_rejects_a_short_key_without_echoing_it(self):
        short_key = "k123"

        response = self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": short_key},
            format="json",
        )
        subsequent_get = self.client.get("/api/account/model-credential/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.data)
        self.assertNotIn(short_key, str(response.data))
        self.assertNotIn(short_key, str(subsequent_get.data))
        self.assertFalse(subsequent_get.data["has_api_key"])
        self.assertEqual(subsequent_get.data["key_last4"], "")

    def test_legacy_put_rejects_an_oversized_key_without_persisting_it(self):
        oversized_key = "k" * 4097

        response = self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": oversized_key},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.data)
        self.assertFalse(UserModelCredential.objects.filter(user=self.user).exclude(encrypted_api_key="").exists())

    def test_legacy_service_rejects_an_incomplete_candidate_before_writing(self):
        from .services.model_profiles import ModelProfileInvalid, update_legacy_model_credential

        credential = UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-secret-1234"),
            key_last4="1234",
        )

        with self.assertRaises(ModelProfileInvalid):
            update_legacy_model_credential(user=self.user, values={"api_url": ""})
        with self.assertRaises(ModelProfileInvalid):
            update_legacy_model_credential(user=self.user, values={"api_key": "k123"})

        credential.refresh_from_db()
        self.assertEqual(credential.api_url, "https://models.example/v1")
        self.assertEqual(credential.key_last4, "1234")

    def test_idna_expansion_over_database_limit_is_rejected_by_both_serializers(self):
        from .services.model_endpoint import ModelEndpointError, parse_model_endpoint

        raw_url = f"https://{'.'.join(['ä'] * 63)}/v1"
        self.assertLess(len(raw_url), 500)
        with self.assertRaises(ModelEndpointError) as caught:
            parse_model_endpoint(raw_url)
        self.assertEqual(caught.exception.code, "model_endpoint_invalid")

        legacy_response = self.client.put(
            "/api/account/model-credential/",
            {"api_url": raw_url, "model": "example-chat", "api_key": "sk-secret-1234"},
            format="json",
        )
        profile_response = self.client.post(
            "/api/account/model-profiles/",
            {
                "name": "IDNA 扩长模型",
                "api_url": raw_url,
                "model": "example-chat",
                "api_key": "sk-secret-1234",
            },
            format="json",
        )

        self.assertEqual(legacy_response.status_code, 400)
        self.assertIn("api_url", legacy_response.data)
        self.assertEqual(profile_response.status_code, 400)
        self.assertIn("api_url", profile_response.data)
        self.assertFalse(UserModelCredential.objects.filter(user=self.user).exclude(api_url="").exists())

    def test_delete_clears_current_users_configuration(self):
        self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": "sk-secret-9999"},
            format="json",
        )
        active = UserModelProfile.objects.get(user=self.user, is_active=True)
        encrypted_key = active.encrypted_api_key
        response = self.client.delete("/api/account/model-credential/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(UserModelCredential.objects.filter(user=self.user).exists())
        self.assertFalse(UserModelProfile.objects.filter(pk=active.pk).exists())
        self.assertFalse(UserModelProfile.objects.filter(encrypted_api_key=encrypted_key).exists())


class ModelProfileApiTests(GatewayNetworkMixin, APITestCase):
    def setUp(self):
        self.configure_gateway_network()
        self.user = User.objects.create_user(username="profile-owner", password="strong-password-123")
        self.client.force_login(self.user)

    def create_profile(self, **overrides):
        payload = {
            "name": "主力模型",
            "api_url": "https://models.example/v1/",
            "model": "chat-primary",
            "api_key": "sk-primary-1234",
        }
        payload.update(overrides)
        return self.client.post("/api/account/model-profiles/", payload, format="json")

    def test_first_profile_is_encrypted_activated_and_projected(self):
        response = self.create_profile()

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_active"])
        self.assertTrue(response.data["has_api_key"])
        self.assertEqual(response.data["key_last4"], "1234")
        self.assertNotIn("api_key", response.data)
        self.assertNotIn("encrypted_api_key", response.data)
        self.assertNotIn("sk-primary-1234", str(response.data))
        profile = UserModelProfile.objects.get(pk=response.data["id"])
        credential = UserModelCredential.objects.get(user=self.user)
        self.assertNotIn("sk-primary-1234", profile.encrypted_api_key)
        self.assertEqual(profile.api_url, "https://models.example/v1")
        self.assertEqual(credential.encrypted_api_key, profile.encrypted_api_key)
        self.assertEqual(credential.model, "chat-primary")

    def test_second_profile_stays_inactive_until_an_idempotent_switch(self):
        first = self.create_profile()
        second = self.create_profile(
            name="备用模型",
            api_url="https://backup.example/v1",
            model="chat-backup",
            api_key="sk-backup-5678",
        )
        self.assertEqual(second.status_code, 201)
        self.assertFalse(second.data["is_active"])
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-primary")

        endpoint = f"/api/account/model-profiles/{second.data['id']}/activate/"
        switched = self.client.post(endpoint, {}, format="json")
        repeated = self.client.post(endpoint, {}, format="json")

        self.assertEqual(switched.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.data["is_active"])
        self.assertEqual(UserModelProfile.objects.filter(user=self.user, is_active=True).count(), 1)
        self.assertFalse(UserModelProfile.objects.get(pk=first.data["id"]).is_active)
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-backup")

    def test_make_active_switches_during_creation(self):
        first = self.create_profile()
        second = self.create_profile(
            name="即时模型",
            model="chat-now",
            api_key="sk-now-9999",
            make_active=True,
        )

        self.assertEqual(second.status_code, 201)
        self.assertTrue(second.data["is_active"])
        self.assertFalse(UserModelProfile.objects.get(pk=first.data["id"]).is_active)
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-now")

    def test_reading_an_already_synced_projection_does_not_change_its_fingerprint_time(self):
        self.create_profile()
        credential = UserModelCredential.objects.get(user=self.user)
        original_updated_at = credential.updated_at

        response = self.client.get("/api/account/model-credential/")

        self.assertEqual(response.status_code, 200)
        credential.refresh_from_db()
        self.assertEqual(credential.updated_at, original_updated_at)

    def test_legacy_write_updates_the_active_profile_without_creating_a_duplicate(self):
        self.create_profile()
        active = self.create_profile(
            name="备用模型",
            model="chat-backup",
            api_key="sk-backup-5678",
            make_active=True,
        )

        response = self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://legacy.example/v1", "model": "legacy-chat", "api_key": "sk-legacy-2468"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserModelProfile.objects.filter(user=self.user).count(), 2)
        profile = UserModelProfile.objects.get(pk=active.data["id"])
        credential = UserModelCredential.objects.get(user=self.user)
        self.assertTrue(profile.is_active)
        self.assertEqual(profile.model, "legacy-chat")
        self.assertEqual(profile.key_last4, "2468")
        self.assertEqual(profile.encrypted_api_key, credential.encrypted_api_key)

    def test_editing_active_profile_preserves_omitted_key_and_updates_projection(self):
        created = self.create_profile()
        profile = UserModelProfile.objects.get(pk=created.data["id"])
        original_encrypted_key = profile.encrypted_api_key

        response = self.client.patch(
            f"/api/account/model-profiles/{profile.pk}/",
            {"name": "主力模型新版", "api_url": "https://new.example/v1/", "model": "chat-new"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        credential = UserModelCredential.objects.get(user=self.user)
        self.assertEqual(profile.encrypted_api_key, original_encrypted_key)
        self.assertEqual(profile.api_url, "https://new.example/v1")
        self.assertEqual(credential.model, "chat-new")
        self.assertEqual(credential.encrypted_api_key, original_encrypted_key)

    def test_editing_inactive_profile_does_not_change_projection(self):
        self.create_profile()
        inactive = self.create_profile(
            name="备用模型",
            model="chat-backup",
            api_key="sk-backup-5678",
        )

        response = self.client.patch(
            f"/api/account/model-profiles/{inactive.data['id']}/",
            {"model": "chat-backup-v2"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-primary")

    def test_patch_cannot_bypass_the_dedicated_activation_action(self):
        self.create_profile()
        inactive = self.create_profile(
            name="备用模型",
            model="chat-backup",
            api_key="sk-backup-5678",
        )

        response = self.client.patch(
            f"/api/account/model-profiles/{inactive.data['id']}/",
            {"make_active": True},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("make_active", response.data)
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-primary")

    def test_names_are_unique_per_user_ignoring_case(self):
        first = self.create_profile(name="Primary")
        duplicate = self.create_profile(name="primary", model="another-chat", api_key="sk-another-5555")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("name", duplicate.data)

    def test_profile_queries_and_actions_are_isolated_by_user(self):
        own = self.create_profile()
        other = User.objects.create_user(username="other-profile-owner", password="strong-password-123")
        foreign = UserModelProfile.objects.create(
            user=other,
            name="他人模型",
            api_url="https://other.example/v1",
            model="other-chat",
            encrypted_api_key=encrypt_secret("sk-other-7777"),
            key_last4="7777",
            is_active=True,
        )

        listed = self.client.get("/api/account/model-profiles/")
        self.assertEqual([item["id"] for item in listed.data], [own.data["id"]])
        self.assertEqual(self.client.get(f"/api/account/model-profiles/{foreign.pk}/").status_code, 404)
        self.assertEqual(
            self.client.patch(f"/api/account/model-profiles/{foreign.pk}/", {"name": "越权"}, format="json").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(f"/api/account/model-profiles/{foreign.pk}/activate/", {}, format="json").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(f"/api/account/model-profiles/{foreign.pk}/test/", {}, format="json").status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"/api/account/model-profiles/{foreign.pk}/").status_code, 404)

    def test_deleting_inactive_profile_erases_only_that_profile(self):
        active = self.create_profile()
        inactive = self.create_profile(
            name="待删除备用模型",
            model="chat-backup",
            api_key="sk-backup-delete-5678",
        )

        response = self.client.delete(f"/api/account/model-profiles/{inactive.data['id']}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(UserModelProfile.objects.filter(pk=inactive.data["id"]).exists())
        self.assertTrue(UserModelProfile.objects.filter(pk=active.data["id"], is_active=True).exists())
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-primary")

    def test_deleting_active_profile_clears_projection_without_auto_switching(self):
        active = self.create_profile()
        inactive = self.create_profile(
            name="保留备用模型",
            model="chat-backup",
            api_key="sk-backup-keep-5678",
        )

        response = self.client.delete(f"/api/account/model-profiles/{active.data['id']}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(UserModelProfile.objects.filter(pk=active.data["id"]).exists())
        self.assertTrue(UserModelProfile.objects.filter(pk=inactive.data["id"], is_active=False).exists())
        self.assertFalse(UserModelCredential.objects.filter(user=self.user).exists())
        listed = self.client.get("/api/account/model-profiles/")
        self.assertEqual(len(listed.data), 1)
        self.assertFalse(listed.data[0]["is_active"])
        self.assertNotIn("encrypted_api_key", str(listed.data))

    def test_new_profile_requires_complete_validated_configuration(self):
        missing_key = self.create_profile(api_key=None)
        invalid_url = self.create_profile(name="另一个模型", api_url="not-a-url", api_key="sk-valid-8888")

        self.assertEqual(missing_key.status_code, 400)
        self.assertIn("api_key", missing_key.data)
        self.assertEqual(invalid_url.status_code, 400)
        self.assertIn("api_url", invalid_url.data)

    def test_profile_post_rejects_a_short_key_without_echoing_it(self):
        short_key = "p123"

        response = self.create_profile(api_key=short_key)
        subsequent_list = self.client.get("/api/account/model-profiles/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.data)
        self.assertNotIn(short_key, str(response.data))
        self.assertNotIn(short_key, str(subsequent_list.data))
        self.assertEqual(subsequent_list.data, [])

    def test_profile_service_rejects_an_oversized_key_even_without_a_serializer(self):
        from .services.model_profiles import ModelProfileInvalid, create_model_profile

        with self.assertRaises(ModelProfileInvalid):
            create_model_profile(
                user=self.user,
                values={
                    "name": "超长密钥模型",
                    "api_url": "https://models.example/v1",
                    "model": "chat-primary",
                    "api_key": "k" * 4097,
                },
            )

        self.assertFalse(UserModelProfile.objects.filter(user=self.user).exists())

    def test_default_endpoint_policy_rejects_restricted_and_ambiguous_urls(self):
        blocked_urls = {
            "plain_http": "http://models.example/v1",
            "ipv4_loopback": "https://127.0.0.1/v1",
            "ipv4_private": "https://10.0.0.8/v1",
            "ipv4_link_local": "https://169.254.169.254/v1",
            "ipv4_unspecified": "https://0.0.0.0/v1",
            "ipv4_multicast": "https://224.0.0.1/v1",
            "ipv4_reserved": "https://192.0.2.10/v1",
            "ipv6_loopback": "https://[::1]/v1",
            "ipv6_private": "https://[fd00::1]/v1",
            "ipv6_link_local": "https://[fe80::1]/v1",
            "ipv6_unspecified": "https://[::]/v1",
            "ipv6_multicast": "https://[ff02::1]/v1",
            "localhost": "https://localhost/v1",
            "localhost_subdomain": "https://api.localhost/v1",
            "userinfo": "https://operator:private-token@models.example/v1",
            "query": "https://models.example/v1?token=private-token",
            "fragment": "https://models.example/v1#private-token",
        }

        for label, api_url in blocked_urls.items():
            with self.subTest(label=label):
                response = self.create_profile(api_url=api_url)
                self.assertEqual(response.status_code, 400)
                self.assertIn("api_url", response.data)
                self.assertNotIn("private-token", str(response.data))

    def test_public_ipv6_literal_is_accepted(self):
        response = self.create_profile(api_url="https://[2606:4700:4700::1111]/v1/")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["api_url"], "https://[2606:4700:4700::1111]/v1")

    @override_settings(MODEL_API_HOST_ALLOWLIST=("127.0.0.1:11434",))
    def test_deployment_allowlist_can_enable_an_exact_local_http_endpoint(self):
        response = self.create_profile(api_url="http://127.0.0.1:11434/v1/")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["api_url"], "http://127.0.0.1:11434/v1")

    def test_first_complete_profile_activates_when_only_partial_inactive_data_exists(self):
        partial = UserModelProfile.objects.create(
            user=self.user,
            name="旧的不完整配置",
            api_url="https://models.example/v1",
            model="",
            encrypted_api_key="",
            is_active=False,
        )

        response = self.create_profile(name="修复后的完整配置")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_active"])
        partial.refresh_from_db()
        self.assertFalse(partial.is_active)
        self.assertEqual(UserModelCredential.objects.get(user=self.user).model, "chat-primary")

    def test_api_url_over_database_limit_is_rejected_before_insert(self):
        too_long_url = "https://models.example/" + ("a" * 500)

        response = self.create_profile(api_url=too_long_url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_url", response.data)

    def test_tests_a_selected_profile_without_exposing_its_secret(self):
        created = self.create_profile()
        self.https_connection.getresponse.return_value = FakeModelResponse(
            {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        )

        response = self.client.post(
            f"/api/account/model-profiles/{created.data['id']}/test/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profile_id"], created.data["id"])
        self.assertEqual(response.data["status"], "available")
        self.assertNotIn("sk-primary-1234", str(response.data))
        self.assertNotIn("api_key", response.data)

    def test_database_rejects_two_active_profiles_for_one_user(self):
        self.create_profile()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserModelProfile.objects.create(
                    user=self.user,
                    name="违规活动模型",
                    api_url="https://invalid.example/v1",
                    model="invalid-chat",
                    encrypted_api_key=encrypt_secret("sk-invalid-0000"),
                    key_last4="0000",
                    is_active=True,
                )


class FakeModelResponse:
    def __init__(self, payload=None, *, status=200, headers=None, body=None):
        self.status = status
        self.headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        self.body = body if body is not None else json.dumps(payload).encode("utf-8")

    def getheader(self, name):
        return self.headers.get(str(name).lower())

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]


class ModelGatewayTests(GatewayNetworkMixin, TestCase):
    def setUp(self):
        self.configure_gateway_network()
        self.user = User.objects.create_user(username="gateway-user", password="strong-password-123")
        self.credential = UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1/",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-private-1234"),
            key_last4="1234",
        )

    def test_calls_openai_compatible_chat_completions_and_parses_json(self):
        from .services.model_gateway import OpenAICompatibleGateway

        self.https_connection.getresponse.return_value = FakeModelResponse(
            {
                "choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            }
        )

        result = OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(result.data, {"ok": True})
        self.assertEqual(result.prompt_tokens, 10)
        self.assertEqual(result.completion_tokens, 4)
        request_args = self.https_connection.request.call_args
        self.assertEqual(request_args.args[:2], ("POST", "/v1/chat/completions"))
        self.assertEqual(request_args.kwargs["headers"]["Authorization"], "Bearer sk-private-1234")
        body = json.loads(request_args.kwargs["body"])
        self.assertEqual(body["model"], "example-chat")
        self.assertEqual(body["temperature"], 0)
        self.assertNotIn("sk-private-1234", json.dumps(body))

    def test_classifies_authentication_failure_without_exposing_the_key(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.getresponse.return_value = FakeModelResponse(status=401, body=b"bad key")

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_auth_failed")
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("sk-private-1234", str(caught.exception))

    def test_classifies_rate_limit_as_retryable(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.getresponse.return_value = FakeModelResponse(status=429, body=b"rate limited")

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_rate_limited")
        self.assertTrue(caught.exception.retryable)

    def test_classifies_timeout_as_retryable(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.connect.side_effect = socket.timeout("timed out")

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_timeout")
        self.assertTrue(caught.exception.retryable)

    def test_rejects_non_json_model_content(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.getresponse.return_value = FakeModelResponse(
            {"choices": [{"message": {"content": "not json"}}], "usage": {}}
        )

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_invalid_response")
        self.assertFalse(caught.exception.retryable)

    def test_private_dns_result_is_rejected_before_connecting(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.20.30.40", 443))
        ]

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="candidate text")

        self.assertEqual(caught.exception.code, "model_endpoint_blocked")
        self.mock_https_connection_class.assert_not_called()

    def test_peer_rebinding_is_rejected_before_sending_secret_or_candidate_text(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.sock.getpeername.return_value = ("127.0.0.1", 443)

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="candidate text")

        self.assertEqual(caught.exception.code, "model_endpoint_blocked")
        self.https_connection.request.assert_not_called()
        self.assertNotIn("sk-private-1234", str(caught.exception))
        self.assertNotIn("candidate text", str(caught.exception))

    def test_connection_is_pinned_to_first_resolution_without_a_second_dns_lookup(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        probe = PinnedConnectionProbe("models.example", 443, timeout=60)
        self.mock_https_connection_class.return_value = probe
        with patch("accounts.services.model_gateway.socket.socket") as socket_class:
            connected_socket = socket_class.return_value
            connected_socket.getpeername.return_value = ("127.0.0.1", 443)

            with self.assertRaises(ModelGatewayError) as caught:
                OpenAICompatibleGateway(self.credential).complete_json(
                    system="system",
                    user="candidate text",
                )

        self.assertEqual(caught.exception.code, "model_endpoint_blocked")
        self.assertEqual(self.mock_getaddrinfo.call_count, 1)
        connected_socket.connect.assert_called_once_with((PUBLIC_IPV4, 443))
        probe.request.assert_not_called()

    def test_redirect_is_not_followed_or_forwarded_to_another_host(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.getresponse.return_value = FakeModelResponse(
            status=302,
            headers={"Location": "https://attacker.example/collect"},
            body=b"redirect",
        )

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="candidate text")

        self.assertEqual(caught.exception.code, "model_redirect_blocked")
        self.assertEqual(self.mock_https_connection_class.call_count, 1)
        self.https_connection.request.assert_called_once()

    @override_settings(MODEL_API_MAX_RESPONSE_BYTES=64)
    def test_response_body_is_capped(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.https_connection.getresponse.return_value = FakeModelResponse(
            headers={"Content-Length": "65"},
            body=b"x" * 65,
        )

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_response_too_large")

    @override_settings(MODEL_API_HOST_ALLOWLIST=("127.0.0.1:11434",))
    def test_allowlisted_private_http_endpoint_can_succeed(self):
        from .services.model_gateway import OpenAICompatibleGateway

        self.credential.api_url = "http://127.0.0.1:11434/v1"
        self.credential.save(update_fields=["api_url", "updated_at"])
        self.mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 11434))
        ]
        with patch("accounts.services.model_gateway.HTTPConnection") as http_connection_class:
            connection = http_connection_class.return_value
            connection.sock.getpeername.return_value = ("127.0.0.1", 11434)
            connection.getresponse.return_value = FakeModelResponse(
                {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}
            )

            result = OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(result.data, {"ok": True})
        self.mock_https_connection_class.assert_not_called()
        connection.request.assert_called_once()

    def test_public_ipv6_endpoint_succeeds_when_dns_and_peer_match(self):
        from .services.model_gateway import OpenAICompatibleGateway

        public_ipv6 = "2606:4700:4700::1111"
        self.credential.api_url = f"https://[{public_ipv6}]/v1"
        self.credential.save(update_fields=["api_url", "updated_at"])
        self.mock_getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (public_ipv6, 443, 0, 0))
        ]
        self.https_connection.sock.getpeername.return_value = (public_ipv6, 443, 0, 0)
        self.https_connection.getresponse.return_value = FakeModelResponse(
            {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}
        )

        result = OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(result.data, {"ok": True})
        self.mock_https_connection_class.assert_called_once()

    def test_gateway_revalidates_a_stored_userinfo_url_before_dns_or_send(self):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        self.credential.api_url = "https://operator:private-token@models.example/v1"
        self.credential.save(update_fields=["api_url", "updated_at"])

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="candidate text")

        self.assertEqual(caught.exception.code, "model_endpoint_invalid")
        self.mock_getaddrinfo.assert_not_called()
        self.mock_https_connection_class.assert_not_called()
        self.assertNotIn("private-token", str(caught.exception))
        self.assertNotIn("sk-private-1234", str(caught.exception))


class ModelConnectionApiTests(GatewayNetworkMixin, APITestCase):
    def setUp(self):
        self.configure_gateway_network()
        self.user = User.objects.create_user(username="connection-user", password="strong-password-123")
        self.client.force_login(self.user)
        UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-connection-5678"),
            key_last4="5678",
        )

    def test_tests_current_users_model_connection_without_returning_secret(self):
        self.https_connection.getresponse.return_value = FakeModelResponse(
            {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
        )

        response = self.client.post("/api/account/model-credential/test/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "available")
        self.assertEqual(response.data["model"], "example-chat")
        self.assertGreaterEqual(response.data["latency_ms"], 0)
        self.assertNotIn("api_key", response.data)
        self.assertNotIn("sk-connection-5678", str(response.data))
        self.assertEqual(self.mock_https_connection_class.call_args.kwargs["timeout"], 10)

    def test_connection_checks_are_throttled_per_user(self):
        self.https_connection.getresponse.return_value = FakeModelResponse(
            {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {},
            }
        )

        responses = [
            self.client.post("/api/account/model-credential/test/", {}, format="json")
            for _ in range(6)
        ]

        self.assertEqual([response.status_code for response in responses[:5]], [200] * 5)
        self.assertEqual(responses[5].status_code, 429)

    def test_requires_a_complete_model_configuration(self):
        UserModelCredential.objects.filter(user=self.user).update(api_url="", encrypted_api_key="")

        response = self.client.post("/api/account/model-credential/test/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "model_not_configured")
