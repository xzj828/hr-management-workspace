from django.contrib.auth.models import User
from django.db import models


class UserModelCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="model_credential")
    api_url = models.URLField(blank=True)
    model = models.CharField(max_length=120, blank=True)
    encrypted_api_key = models.TextField(blank=True)
    key_last4 = models.CharField(max_length=4, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} / {self.model or 'unconfigured'}"
