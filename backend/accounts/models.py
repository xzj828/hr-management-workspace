from django.contrib.auth.models import User
from django.db import models
from django.db.models.functions import Lower


class UserModelProfile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="model_profiles")
    name = models.CharField(max_length=80)
    api_url = models.URLField(blank=True, max_length=500)
    model = models.CharField(max_length=120, blank=True)
    encrypted_api_key = models.TextField(blank=True)
    key_last4 = models.CharField(max_length=4, blank=True)
    is_active = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "user",
                name="unique_user_model_profile_name_ci",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_active=True),
                name="unique_active_model_profile_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} / {self.name}"


class UserModelCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="model_credential")
    api_url = models.URLField(blank=True, max_length=500)
    model = models.CharField(max_length=120, blank=True)
    encrypted_api_key = models.TextField(blank=True)
    key_last4 = models.CharField(max_length=4, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} / {self.model or 'unconfigured'}"
