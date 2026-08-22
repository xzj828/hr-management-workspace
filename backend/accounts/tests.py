from django.contrib.auth.models import User
from rest_framework.test import APITestCase

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
