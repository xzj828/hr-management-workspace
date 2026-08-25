import json
import socket
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APITestCase

from .crypto import encrypt_secret
from .models import UserModelCredential


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

    def test_delete_clears_current_users_configuration(self):
        self.client.put(
            "/api/account/model-credential/",
            {"api_url": "https://models.example/v1", "model": "example-chat", "api_key": "sk-secret-9999"},
            format="json",
        )
        response = self.client.delete("/api/account/model-credential/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(UserModelCredential.objects.filter(user=self.user).exists())


class FakeModelResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ModelGatewayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="gateway-user", password="strong-password-123")
        self.credential = UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1/",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-private-1234"),
            key_last4="1234",
        )

    @patch("accounts.services.model_gateway.urlopen")
    def test_calls_openai_compatible_chat_completions_and_parses_json(self, mocked_urlopen):
        from .services.model_gateway import OpenAICompatibleGateway

        mocked_urlopen.return_value = FakeModelResponse(
            {
                "choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            }
        )

        result = OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(result.data, {"ok": True})
        self.assertEqual(result.prompt_tokens, 10)
        self.assertEqual(result.completion_tokens, 4)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://models.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-private-1234")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "example-chat")
        self.assertEqual(body["temperature"], 0)
        self.assertNotIn("sk-private-1234", json.dumps(body))

    @patch("accounts.services.model_gateway.urlopen")
    def test_classifies_authentication_failure_without_exposing_the_key(self, mocked_urlopen):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        mocked_urlopen.side_effect = HTTPError(
            "https://models.example/v1/chat/completions", 401, "Unauthorized sk-private-1234", {}, BytesIO(b"bad key")
        )

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_auth_failed")
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("sk-private-1234", str(caught.exception))

    @patch("accounts.services.model_gateway.urlopen")
    def test_classifies_rate_limit_as_retryable(self, mocked_urlopen):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        mocked_urlopen.side_effect = HTTPError(
            "https://models.example/v1/chat/completions", 429, "Too Many Requests", {}, BytesIO(b"rate limited")
        )

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_rate_limited")
        self.assertTrue(caught.exception.retryable)

    @patch("accounts.services.model_gateway.urlopen")
    def test_classifies_timeout_as_retryable(self, mocked_urlopen):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        mocked_urlopen.side_effect = socket.timeout("timed out")

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_timeout")
        self.assertTrue(caught.exception.retryable)

    @patch("accounts.services.model_gateway.urlopen")
    def test_rejects_non_json_model_content(self, mocked_urlopen):
        from .services.model_gateway import ModelGatewayError, OpenAICompatibleGateway

        mocked_urlopen.return_value = FakeModelResponse(
            {"choices": [{"message": {"content": "not json"}}], "usage": {}}
        )

        with self.assertRaises(ModelGatewayError) as caught:
            OpenAICompatibleGateway(self.credential).complete_json(system="system", user="user")

        self.assertEqual(caught.exception.code, "model_invalid_response")
        self.assertFalse(caught.exception.retryable)


class ModelConnectionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="connection-user", password="strong-password-123")
        self.client.force_login(self.user)
        UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-connection-5678"),
            key_last4="5678",
        )

    @patch("accounts.services.model_gateway.urlopen")
    def test_tests_current_users_model_connection_without_returning_secret(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeModelResponse(
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

    def test_requires_a_complete_model_configuration(self):
        UserModelCredential.objects.filter(user=self.user).update(api_url="", encrypted_api_key="")

        response = self.client.post("/api/account/model-credential/test/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "model_not_configured")
