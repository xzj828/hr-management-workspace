# HR Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing attendance workbench into the first working slice of the Ximing HR platform with two-level navigation, recruitment foundations, remembered login, and encrypted per-user model credentials.

**Architecture:** Keep Vue 3 as the only frontend and Django/DRF as the unified business backend. Add focused `accounts` and `recruitment` Django apps while preserving the existing `attendance` app; this phase creates stable routes, models, permissions, and UI seams before the RPA worker and full recruitment workflows are implemented in later plans.

**Tech Stack:** Python 3.14, Django 5.2, Django REST Framework 3.16, SQLite, cryptography/Fernet, Vue 3, Pinia, Vue Router, Vitest, Vue Test Utils, Vite.

---

## Scope and follow-on plans

This specification contains four independently testable subsystems. This plan covers subsystem 1 only and leaves the repository in a working, deployable state:

1. **This plan:** unified shell, account security, recruitment foundation, remembered login, model credential persistence, and Copilot UI seam.
2. **Follow-on plan:** recruitment pipeline, interviews, offers, conversion to employee, resumes, and audit history.
3. **Follow-on plan:** Windows RPA worker, multi-account Chrome isolation, task queue, throttling, retry, and circuit breaking.
4. **Follow-on plan:** resume parsing/OCR, evidence extraction contract, deterministic scoring, and real Copilot backend.

No third-party candidate registry, resume image, or score report from the supplied ZIP is copied into this repository.

## File map

### Backend files created

- `backend/accounts/__init__.py` — accounts app package.
- `backend/accounts/apps.py` — Django app registration.
- `backend/accounts/models.py` — encrypted per-user model credential metadata.
- `backend/accounts/crypto.py` — API key encryption and decryption boundary.
- `backend/accounts/serializers.py` — masked credential API representation and writes.
- `backend/accounts/views.py` — current-user credential endpoint.
- `backend/accounts/urls.py` — accounts endpoint routes.
- `backend/accounts/tests.py` — encryption, masking, ownership, and persistence tests.
- `backend/recruitment/__init__.py` — recruitment app package.
- `backend/recruitment/apps.py` — Django app registration.
- `backend/recruitment/models.py` — BOSS account, position, candidate, and application foundations.
- `backend/recruitment/serializers.py` — foundation API serializers.
- `backend/recruitment/permissions.py` — recruitment role permissions.
- `backend/recruitment/views.py` — initial viewsets and dashboard summary.
- `backend/recruitment/urls.py` — recruitment API routes.
- `backend/recruitment/tests.py` — model constraints, permissions, and dashboard tests.

### Backend files modified

- `backend/requirements.txt` — add `cryptography`.
- `backend/config/settings.py` — register new apps and remembered-session defaults.
- `backend/config/urls.py` — mount accounts and recruitment APIs.
- `backend/attendance/views.py` — accept the `remember` login option.
- `backend/attendance/tests.py` — verify short and remembered login behavior.

### Frontend files created

- `frontend/src/navigation.js` — single source of truth for top-level modules and side navigation.
- `frontend/src/navigation.test.js` — navigation mapping tests.
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue` — first recruitment dashboard shell.
- `frontend/src/views/recruitment/RecruitmentPlaceholderView.vue` — stable placeholder for later recruitment pages.
- `frontend/src/components/RecruitmentCopilotDrawer.vue` — model configuration and future Copilot entry.
- `frontend/src/stores/modelCredential.js` — masked model credential state.

### Frontend files modified

- `frontend/src/router.js` — attendance and recruitment route trees.
- `frontend/src/components/AppLayout.vue` — top module switcher and contextual side navigation.
- `frontend/src/views/LoginView.vue` — HR platform branding and remember-login checkbox.
- `frontend/src/stores/auth.js` — send the remember flag.
- `frontend/src/App.vue` — HR platform loading copy.
- `frontend/src/styles.css` — module switcher, Copilot drawer, and foundation page styling.

---

### Task 1: Establish a protected baseline

**Files:**
- Modify: `.gitignore`
- Verify: existing backend and frontend test suites

- [ ] **Step 1: Add local runtime artifacts to `.gitignore`**

Append these exact rules:

```gitignore
.coverage
htmlcov/
backend/*.log
frontend/coverage/
```

- [ ] **Step 2: Run the existing backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test attendance --verbosity 1
```

Expected: 4 tests pass and Django reports no system-check issues.

- [ ] **Step 3: Run the existing frontend tests**

Run from `frontend`:

```powershell
npm test
```

Expected: `src/api.test.js` passes both tests.

- [ ] **Step 4: Initialize version control and record the baseline**

Run only after confirming `.git` is absent:

```powershell
git init
git add .
git commit -m "chore: capture hr platform baseline"
```

Expected: the initial commit succeeds without adding `.venv`, `db.sqlite3`, `media`, `staticfiles`, `frontend_dist`, `local_secret.key`, or `node_modules`.

### Task 2: Add remembered login semantics

**Files:**
- Modify: `backend/attendance/tests.py`
- Modify: `backend/attendance/views.py`
- Modify: `backend/config/settings.py`

- [ ] **Step 1: Write failing login-expiry tests**

Add to `backend/attendance/tests.py`:

```python
from django.contrib.auth.models import User
from rest_framework.test import APITestCase


class LoginSessionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="session-user", password="strong-password-123")

    def test_normal_login_expires_at_browser_close(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "strong-password-123", "remember": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_remembered_login_uses_thirty_day_session(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "strong-password-123", "remember": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertGreaterEqual(self.client.session.get_expiry_age(), 29 * 24 * 60 * 60)
```

- [ ] **Step 2: Run the tests and verify the remembered-session test fails**

Run:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test attendance.tests.LoginSessionTests --verbosity 2
```

Expected: `test_remembered_login_uses_thirty_day_session` fails because the login view does not set session expiry.

- [ ] **Step 3: Implement explicit session expiry**

In `backend/config/settings.py`, add:

```python
SESSION_COOKIE_AGE = 30 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
```

In `backend/attendance/views.py`, immediately after `login(request, user)` add:

```python
    remember = bool(request.data.get("remember", False))
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember else 0)
```

Add the import:

```python
from django.conf import settings
```

- [ ] **Step 4: Run the focused and full backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test attendance.tests.LoginSessionTests attendance --verbosity 1
```

Expected: all login and attendance tests pass.

- [ ] **Step 5: Commit remembered login**

```powershell
git add backend/attendance/tests.py backend/attendance/views.py backend/config/settings.py
git commit -m "feat: add remembered login sessions"
```

### Task 3: Add encrypted per-user model credentials

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/accounts/__init__.py`
- Create: `backend/accounts/apps.py`
- Create: `backend/accounts/models.py`
- Create: `backend/accounts/crypto.py`
- Create: `backend/accounts/serializers.py`
- Create: `backend/accounts/views.py`
- Create: `backend/accounts/urls.py`
- Create: `backend/accounts/tests.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/config/urls.py`

- [ ] **Step 1: Add the encryption dependency**

Append to `backend/requirements.txt`:

```text
cryptography>=46,<47
```

Install it:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
```

Expected: `cryptography` installs successfully.

- [ ] **Step 2: Create the accounts app skeleton**

Create `backend/accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
```

Create an empty `backend/accounts/__init__.py` and add `"accounts"` to `INSTALLED_APPS` before `"attendance"` in `backend/config/settings.py`.

- [ ] **Step 3: Write failing credential API tests**

Create `backend/accounts/tests.py`:

```python
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
```

- [ ] **Step 4: Run tests and verify they fail because the model and endpoint do not exist**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test accounts --verbosity 2
```

Expected: import or model errors referring to `UserModelCredential`.

- [ ] **Step 5: Implement encrypted storage**

Create `backend/accounts/models.py`:

```python
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
```

Create `backend/accounts/crypto.py`:

```python
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored model credential cannot be decrypted") from exc
```

- [ ] **Step 6: Implement the masked API**

Create `backend/accounts/serializers.py`:

```python
from rest_framework import serializers

from .crypto import encrypt_secret
from .models import UserModelCredential


class UserModelCredentialSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False)
    has_api_key = serializers.SerializerMethodField()

    class Meta:
        model = UserModelCredential
        fields = ["api_url", "model", "api_key", "has_api_key", "key_last4", "updated_at"]
        read_only_fields = ["has_api_key", "key_last4", "updated_at"]

    def get_has_api_key(self, obj):
        return bool(obj.encrypted_api_key)

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        if api_key:
            instance.encrypted_api_key = encrypt_secret(api_key)
            instance.key_last4 = api_key[-4:]
        return super().update(instance, validated_data)
```

Create `backend/accounts/views.py`:

```python
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import UserModelCredential
from .serializers import UserModelCredentialSerializer


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def model_credential_view(request):
    credential, _ = UserModelCredential.objects.get_or_create(user=request.user)
    if request.method == "GET":
        return Response(UserModelCredentialSerializer(credential).data)
    if request.method == "DELETE":
        credential.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = UserModelCredentialSerializer(credential, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)
```

Create `backend/accounts/urls.py`:

```python
from django.urls import path

from .views import model_credential_view


urlpatterns = [
    path("model-credential/", model_credential_view),
]
```

Mount it in `backend/config/urls.py`:

```python
path("api/account/", include("accounts.urls")),
```

- [ ] **Step 7: Create and apply the migration**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py makemigrations accounts
.\.venv\Scripts\python.exe .\backend\manage.py migrate
```

Expected: the `accounts` initial migration is created and applied.

- [ ] **Step 8: Run credential and attendance tests**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test accounts attendance --verbosity 1
```

Expected: all tests pass and no response contains a complete API key.

- [ ] **Step 9: Commit credential persistence**

```powershell
git add backend/accounts backend/config backend/requirements.txt
git commit -m "feat: store model credentials securely per user"
```

### Task 4: Create recruitment foundation models

**Files:**
- Create: `backend/recruitment/__init__.py`
- Create: `backend/recruitment/apps.py`
- Create: `backend/recruitment/models.py`
- Create: `backend/recruitment/tests.py`
- Modify: `backend/config/settings.py`

- [ ] **Step 1: Create the app skeleton and register it**

Create `backend/recruitment/apps.py`:

```python
from django.apps import AppConfig


class RecruitmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "recruitment"
```

Create an empty `backend/recruitment/__init__.py` and add `"recruitment"` after `"attendance"` in `INSTALLED_APPS`.

- [ ] **Step 2: Write failing model tests**

Create `backend/recruitment/tests.py`:

```python
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob


class RecruitmentFoundationModelTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="recruiter")
        self.account = BossAccount.objects.create(
            name="北京招聘账号",
            browser_profile="boss-beijing",
            cdp_port=53470,
            daily_contact_limit=50,
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="boss-job-1",
            title="实施工程师",
            owner=self.hr,
        )
        self.candidate = Candidate.objects.create(
            identity_key="boss-beijing:candidate-1",
            external_id="candidate-1",
            name="测试候选人",
        )

    def test_account_cdp_port_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BossAccount.objects.create(name="重复端口", browser_profile="other", cdp_port=53470)

    def test_candidate_can_apply_to_multiple_jobs(self):
        first = JobApplication.objects.create(candidate=self.candidate, job=self.job, source="recommend")
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="boss-job-2",
            title="运维工程师",
            owner=self.hr,
        )
        second = JobApplication.objects.create(candidate=self.candidate, job=second_job, source="search")
        self.assertNotEqual(first.id, second.id)

    def test_duplicate_application_is_rejected(self):
        JobApplication.objects.create(candidate=self.candidate, job=self.job, source="recommend")
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobApplication.objects.create(candidate=self.candidate, job=self.job, source="search")
```

- [ ] **Step 3: Run tests and verify they fail because the models do not exist**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 2
```

Expected: import errors for the recruitment models.

- [ ] **Step 4: Implement the foundation models**

Create `backend/recruitment/models.py`:

```python
from django.contrib.auth.models import User
from django.db import models


class BossAccount(models.Model):
    class Status(models.TextChoices):
        OFFLINE = "offline", "离线"
        READY = "ready", "可用"
        RUNNING = "running", "执行中"
        PAUSED = "paused", "已暂停"
        RISK = "risk", "风控"

    name = models.CharField(max_length=100, unique=True)
    browser_profile = models.SlugField(max_length=80, unique=True)
    cdp_port = models.PositiveIntegerField(unique=True)
    daily_contact_limit = models.PositiveIntegerField(default=50)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    active = models.BooleanField(default=True)
    authorized_users = models.ManyToManyField(User, blank=True, related_name="boss_accounts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RecruitmentJob(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "招聘中"
        PAUSED = "paused", "已暂停"
        CLOSED = "closed", "已关闭"

    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="jobs")
    external_id = models.CharField(max_length=120)
    title = models.CharField(max_length=120)
    department = models.CharField(max_length=100, blank=True)
    jd = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recruitment_jobs")
    headcount = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["boss_account", "external_id"], name="unique_boss_job")
        ]


class Candidate(models.Model):
    identity_key = models.CharField(max_length=255, unique=True)
    external_id = models.CharField(max_length=120, blank=True)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    current_title = models.CharField(max_length=120, blank=True)
    current_city = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class JobApplication(models.Model):
    class Stage(models.TextChoices):
        NEW = "new", "新候选人"
        TO_CONTACT = "to_contact", "待联系"
        GREETED = "greeted", "已打招呼"
        COMMUNICATING = "communicating", "沟通中"
        WAITING_RESUME = "waiting_resume", "待简历"
        RESUME_RECEIVED = "resume_received", "已收简历"
        TO_SCREEN = "to_screen", "待筛选"
        TO_INTERVIEW = "to_interview", "待面试"
        INTERVIEWING = "interviewing", "面试中"
        TO_OFFER = "to_offer", "待 Offer"
        HIRED = "hired", "已录用"
        REJECTED = "rejected", "已淘汰"
        TALENT_POOL = "talent_pool", "人才库"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="applications")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, related_name="applications")
    source = models.CharField(max_length=30)
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.NEW)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="candidate_applications")
    priority = models.PositiveSmallIntegerField(default=0)
    last_interaction_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["candidate", "job"], name="unique_candidate_job_application")
        ]
```

- [ ] **Step 5: Create migrations and run model tests**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py makemigrations recruitment
.\.venv\Scripts\python.exe .\backend\manage.py migrate
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 1
```

Expected: all three recruitment model tests pass.

- [ ] **Step 6: Commit recruitment foundations**

```powershell
git add backend/recruitment backend/config/settings.py
git commit -m "feat: add recruitment foundation models"
```

### Task 5: Expose recruitment foundation APIs with role enforcement

**Files:**
- Create: `backend/recruitment/permissions.py`
- Create: `backend/recruitment/serializers.py`
- Create: `backend/recruitment/views.py`
- Create: `backend/recruitment/urls.py`
- Modify: `backend/recruitment/tests.py`
- Modify: `backend/config/urls.py`

- [ ] **Step 1: Add failing API permission and dashboard tests**

Append to `backend/recruitment/tests.py`:

```python
from attendance.models import AccountProfile
from rest_framework.test import APITestCase


class RecruitmentFoundationApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="hr-api")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.viewer = User.objects.create_user(username="viewer-api")
        AccountProfile.objects.create(user=self.viewer, role=AccountProfile.Role.VIEWER)

    def test_hr_can_create_boss_account(self):
        self.client.force_login(self.hr)
        response = self.client.post(
            "/api/recruitment/boss-accounts/",
            {"name": "主招聘账号", "browser_profile": "main-boss", "cdp_port": 53470, "daily_contact_limit": 40},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_viewer_cannot_create_boss_account(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            "/api/recruitment/boss-accounts/",
            {"name": "禁止创建", "browser_profile": "blocked", "cdp_port": 53471},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_authenticated_user_can_read_empty_dashboard(self):
        self.client.force_login(self.viewer)
        response = self.client.get("/api/recruitment/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["open_jobs"], 0)
        self.assertEqual(response.data["active_candidates"], 0)
```

- [ ] **Step 2: Run focused tests and verify endpoint failures**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.RecruitmentFoundationApiTests --verbosity 2
```

Expected: 404 responses because recruitment URLs do not exist.

- [ ] **Step 3: Implement permissions and serializers**

Create `backend/recruitment/permissions.py`:

```python
from rest_framework.permissions import SAFE_METHODS, BasePermission

from attendance.permissions import is_hr_user


class RecruitmentWritePermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return is_hr_user(request.user)
```

Create `backend/recruitment/serializers.py`:

```python
from rest_framework import serializers

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob


class BossAccountSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = BossAccount
        fields = ["id", "name", "browser_profile", "cdp_port", "daily_contact_limit", "status", "status_label", "active"]


class RecruitmentJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitmentJob
        fields = ["id", "boss_account", "external_id", "title", "department", "jd", "owner", "headcount", "status", "created_at", "updated_at"]


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = ["id", "identity_key", "external_id", "name", "phone", "email", "current_title", "current_city", "created_at", "updated_at"]


class JobApplicationSerializer(serializers.ModelSerializer):
    candidate = CandidateSerializer(read_only=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = JobApplication
        fields = ["id", "candidate", "job", "source", "stage", "stage_label", "owner", "priority", "last_interaction_at", "created_at", "updated_at"]
```

- [ ] **Step 4: Implement viewsets and dashboard endpoint**

Create `backend/recruitment/views.py`:

```python
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob
from .permissions import RecruitmentWritePermission
from .serializers import BossAccountSerializer, CandidateSerializer, JobApplicationSerializer, RecruitmentJobSerializer


class BossAccountViewSet(viewsets.ModelViewSet):
    queryset = BossAccount.objects.all().order_by("name")
    serializer_class = BossAccountSerializer
    permission_classes = [RecruitmentWritePermission]


class RecruitmentJobViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentJob.objects.select_related("boss_account", "owner").all().order_by("-updated_at")
    serializer_class = RecruitmentJobSerializer
    permission_classes = [RecruitmentWritePermission]


class CandidateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Candidate.objects.all().order_by("-updated_at")
    serializer_class = CandidateSerializer
    permission_classes = [RecruitmentWritePermission]


class JobApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobApplication.objects.select_related("candidate", "job", "owner").all().order_by("-updated_at")
    serializer_class = JobApplicationSerializer
    permission_classes = [RecruitmentWritePermission]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    terminal = [JobApplication.Stage.HIRED, JobApplication.Stage.REJECTED, JobApplication.Stage.TALENT_POOL]
    return Response({
        "open_jobs": RecruitmentJob.objects.filter(status=RecruitmentJob.Status.OPEN).count(),
        "active_candidates": JobApplication.objects.exclude(stage__in=terminal).count(),
        "waiting_resumes": JobApplication.objects.filter(stage=JobApplication.Stage.WAITING_RESUME).count(),
        "waiting_interviews": JobApplication.objects.filter(stage=JobApplication.Stage.TO_INTERVIEW).count(),
        "boss_accounts_ready": BossAccount.objects.filter(status=BossAccount.Status.READY, active=True).count(),
    })
```

Create `backend/recruitment/urls.py`:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("boss-accounts", views.BossAccountViewSet, basename="boss-account")
router.register("jobs", views.RecruitmentJobViewSet, basename="recruitment-job")
router.register("candidates", views.CandidateViewSet, basename="candidate")
router.register("applications", views.JobApplicationViewSet, basename="job-application")

urlpatterns = [
    path("dashboard/", views.dashboard_view),
    path("", include(router.urls)),
]
```

Mount it in `backend/config/urls.py`:

```python
path("api/recruitment/", include("recruitment.urls")),
```

- [ ] **Step 5: Run recruitment and attendance API tests**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment attendance --verbosity 1
```

Expected: HR writes succeed, viewer writes return 403, dashboard reads succeed, and attendance tests remain green.

- [ ] **Step 6: Commit recruitment APIs**

```powershell
git add backend/recruitment backend/config/urls.py
git commit -m "feat: expose recruitment foundation api"
```

### Task 6: Add module-aware Vue navigation

**Files:**
- Create: `frontend/src/navigation.js`
- Create: `frontend/src/navigation.test.js`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/components/AppLayout.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing pure navigation tests**

Create `frontend/src/navigation.test.js`:

```javascript
import { describe, expect, it } from 'vitest'
import { moduleForRoute, navigationForModule } from './navigation'

describe('HR platform navigation', () => {
  it('maps recruitment routes to the recruitment module', () => {
    expect(moduleForRoute({ meta: { module: 'recruitment' } })).toBe('recruitment')
  })

  it('keeps six recruitment side-navigation items', () => {
    expect(navigationForModule('recruitment').map((item) => item.label)).toEqual([
      '招聘看板', '职位管理', '候选人', '招聘流程', '自动化任务', '简历中心',
    ])
  })

  it('keeps the existing six attendance entries', () => {
    expect(navigationForModule('attendance')).toHaveLength(6)
  })
})
```

- [ ] **Step 2: Run the test and verify it fails because `navigation.js` is absent**

Run from `frontend`:

```powershell
npm test -- src/navigation.test.js
```

Expected: module resolution fails for `./navigation`.

- [ ] **Step 3: Implement the navigation source of truth**

Create `frontend/src/navigation.js`:

```javascript
export const modules = [
  { id: 'recruitment', label: '招聘管理', routeName: 'recruitment-dashboard' },
  { id: 'attendance', label: '考勤管理', routeName: 'attendance-dashboard' },
]

const navigation = {
  recruitment: [
    { name: 'recruitment-dashboard', label: '招聘看板', icon: '⌁' },
    { name: 'recruitment-jobs', label: '职位管理', icon: '▣' },
    { name: 'recruitment-candidates', label: '候选人', icon: '◎' },
    { name: 'recruitment-pipeline', label: '招聘流程', icon: '◇' },
    { name: 'recruitment-automation', label: '自动化任务', icon: '⇄' },
    { name: 'recruitment-resumes', label: '简历中心', icon: '▤' },
  ],
  attendance: [
    { name: 'attendance-dashboard', label: '考勤看板', icon: '⌁' },
    { name: 'employees', label: '人员管理', icon: '◎' },
    { name: 'imports', label: '导入中心', icon: '⇧' },
    { name: 'results', label: '核算结果', icon: '✓' },
    { name: 'suspicions', label: '异常审核', icon: '!' },
    { name: 'settings', label: '规则与标签', icon: '⚙' },
  ],
}

export function moduleForRoute(route) {
  return route.meta?.module || 'attendance'
}

export function navigationForModule(moduleId) {
  return navigation[moduleId] || navigation.attendance
}
```

- [ ] **Step 4: Replace the router with two module trees**

Update `frontend/src/router.js` so the authenticated layout contains these routes:

```javascript
{
  path: '/',
  component: AppLayout,
  children: [
    { path: '', redirect: { name: 'attendance-dashboard' } },
    { path: 'attendance', name: 'attendance-dashboard', component: () => import('@/views/DashboardView.vue'), meta: { module: 'attendance', title: '考勤看板' } },
    { path: 'employees', name: 'employees', component: () => import('@/views/EmployeesView.vue'), meta: { module: 'attendance', title: '人员管理' } },
    { path: 'imports', name: 'imports', component: () => import('@/views/ImportsView.vue'), meta: { module: 'attendance', title: '导入中心' } },
    { path: 'results', name: 'results', component: () => import('@/views/ResultsView.vue'), meta: { module: 'attendance', title: '核算结果' } },
    { path: 'suspicions', name: 'suspicions', component: () => import('@/views/SuspicionsView.vue'), meta: { module: 'attendance', title: '异常审核' } },
    { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { module: 'attendance', title: '规则与标签' } },
    { path: 'recruitment', name: 'recruitment-dashboard', component: () => import('@/views/recruitment/RecruitmentDashboardView.vue'), meta: { module: 'recruitment', title: '招聘看板' } },
    { path: 'recruitment/jobs', name: 'recruitment-jobs', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '职位管理' } },
    { path: 'recruitment/candidates', name: 'recruitment-candidates', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '候选人' } },
    { path: 'recruitment/pipeline', name: 'recruitment-pipeline', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '招聘流程' } },
    { path: 'recruitment/automation', name: 'recruitment-automation', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '自动化任务' } },
    { path: 'recruitment/resumes', name: 'recruitment-resumes', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '简历中心' } },
  ],
}
```

- [ ] **Step 5: Update `AppLayout.vue` to use contextual navigation**

Import:

```javascript
import { modules, moduleForRoute, navigationForModule } from '@/navigation'
```

Replace the static navigation with:

```javascript
const currentModule = computed(() => moduleForRoute(route))
const navigation = computed(() => navigationForModule(currentModule.value))
const currentTitle = computed(() => route.meta?.title || '人事管理')
```

Add this module switcher inside the top bar before the user chip:

```vue
<nav class="module-switcher" aria-label="业务模块">
  <router-link
    v-for="module in modules"
    :key="module.id"
    :to="{ name: module.routeName }"
    :class="{ active: currentModule === module.id }"
  >{{ module.label }}</router-link>
</nav>
```

Change the brand copy to:

```vue
<strong>西鸣人事</strong>
<span>People OS</span>
```

Change `v-for="item in navigation"` to `v-for="item in navigation"` with Vue automatically unwrapping the computed ref in the template.

- [ ] **Step 6: Update loading copy and styles**

Change `frontend/src/App.vue` loading text to:

```vue
<p>正在进入人事管理系统…</p>
```

Append to `frontend/src/styles.css`:

```css
.module-switcher { display: inline-flex; align-items: center; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: 11px; background: #f8fafc; }
.module-switcher a { min-height: 32px; display: inline-flex; align-items: center; padding: 0 13px; border-radius: 8px; color: var(--muted); font-size: 12px; font-weight: 700; }
.module-switcher a:hover { color: var(--ink); }
.module-switcher a.active { color: #fff; background: var(--ink); box-shadow: 0 5px 12px rgba(15,23,42,.12); }
.foundation-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; }
.foundation-card { min-height: 118px; display: flex; flex-direction: column; justify-content: center; padding: 20px; background: var(--paper); border: 1px solid var(--line); border-radius: 15px; }
.foundation-card span { color: var(--muted); font-size: 11px; }
.foundation-card strong { margin-top: 7px; color: var(--ink); font-size: 30px; }
.empty-state-panel { min-height: 420px; display: grid; place-content: center; justify-items: center; padding: 32px; text-align: center; background: var(--paper); border: 1px dashed #cbd5e1; border-radius: 15px; }
.empty-state-panel h2 { margin: 10px 0 7px; color: var(--ink); }
.empty-state-panel p { max-width: 520px; margin: 0; color: var(--muted); line-height: 1.7; }

@media (max-width: 1100px) {
  .foundation-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .topbar { height: auto; min-height: 88px; flex-wrap: wrap; gap: 12px; padding-top: 14px; padding-bottom: 14px; }
}
```

- [ ] **Step 7: Run navigation tests**

```powershell
npm test -- src/navigation.test.js src/api.test.js
```

Expected: all five frontend tests pass.

- [ ] **Step 8: Commit module navigation**

```powershell
git add frontend/src
git commit -m "feat: add hr platform module navigation"
```

### Task 7: Add recruitment dashboard shell and Copilot configuration UI

**Files:**
- Create: `frontend/src/views/recruitment/RecruitmentDashboardView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentPlaceholderView.vue`
- Create: `frontend/src/components/RecruitmentCopilotDrawer.vue`
- Create: `frontend/src/stores/modelCredential.js`
- Modify: `frontend/src/components/AppLayout.vue`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Create the model credential store**

Create `frontend/src/stores/modelCredential.js`:

```javascript
import { defineStore } from 'pinia'
import { api } from '@/api'

export const useModelCredentialStore = defineStore('modelCredential', {
  state: () => ({
    config: { api_url: '', model: '', has_api_key: false, key_last4: '' },
    loading: false,
  }),
  actions: {
    async load() {
      this.loading = true
      try {
        this.config = await api('account/model-credential/')
      } finally {
        this.loading = false
      }
    },
    async save(payload) {
      this.config = await api('account/model-credential/', { method: 'PUT', body: JSON.stringify(payload) })
    },
    async clear() {
      await api('account/model-credential/', { method: 'DELETE' })
      this.config = { api_url: '', model: '', has_api_key: false, key_last4: '' }
    },
  },
})
```

- [ ] **Step 2: Create the Copilot drawer**

Create `frontend/src/components/RecruitmentCopilotDrawer.vue` with:

```vue
<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useModelCredentialStore } from '@/stores/modelCredential'

const emit = defineEmits(['close'])
const credentials = useModelCredentialStore()
const form = reactive({ api_url: '', model: '', api_key: '' })
const message = ref('')

onMounted(async () => {
  await credentials.load()
  form.api_url = credentials.config.api_url || ''
  form.model = credentials.config.model || ''
})

async function save() {
  const payload = { api_url: form.api_url.trim(), model: form.model.trim() }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  await credentials.save(payload)
  form.api_key = ''
  message.value = '模型配置已安全保存；真实 Copilot 后端将在后续阶段接入。'
}
</script>

<template>
  <div class="drawer-backdrop" @click.self="emit('close')">
    <aside class="copilot-drawer" aria-label="招聘 Copilot">
      <header><div><span class="eyebrow">Recruiting Copilot</span><h2>招聘助手</h2></div><button class="ghost-button" @click="emit('close')">关闭</button></header>
      <p class="muted">本阶段保存模型配置并展示交互入口，不会发送简历或调用模型。</p>
      <label class="field-label">API 地址<input v-model="form.api_url" placeholder="https://api.example.com/v1" /></label>
      <label class="field-label">模型名称<input v-model="form.model" placeholder="model-name" /></label>
      <label class="field-label">API Key<input v-model="form.api_key" type="password" autocomplete="off" :placeholder="credentials.config.has_api_key ? `已保存 ····${credentials.config.key_last4}` : '请输入 API Key'" /></label>
      <div class="copilot-actions"><button class="primary-button" @click="save">保存配置</button><button class="ghost-button" disabled>测试连接（待接入）</button></div>
      <p v-if="message" class="success-note">{{ message }}</p>
      <section class="copilot-capabilities">
        <button disabled>总结候选人</button><button disabled>对照 JD 分析</button><button disabled>生成面试问题</button><button disabled>生成沟通话术</button>
      </section>
    </aside>
  </div>
</template>
```

- [ ] **Step 3: Create the dashboard and placeholder pages**

Create `frontend/src/views/recruitment/RecruitmentDashboardView.vue`:

```vue
<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api'

const summary = reactive({ open_jobs: 0, active_candidates: 0, waiting_resumes: 0, waiting_interviews: 0, boss_accounts_ready: 0 })
const error = ref('')

onMounted(async () => {
  try {
    Object.assign(summary, await api('recruitment/dashboard/'))
  } catch (err) {
    error.value = err.message
  }
})

const cards = [
  ['open_jobs', '在招职位'],
  ['active_candidates', '活跃候选人'],
  ['waiting_resumes', '待收简历'],
  ['waiting_interviews', '待安排面试'],
  ['boss_accounts_ready', '可用 BOSS 账号'],
]
</script>

<template>
  <div class="page-stack">
    <header class="page-hero">
      <div><span class="eyebrow">Recruitment Overview</span><h2>招聘看板</h2><p>统一查看职位、候选人、简历和自动化运行状态。</p></div>
    </header>
    <p v-if="error" class="form-error">{{ error }}</p>
    <section class="foundation-grid">
      <article v-for="([key, label]) in cards" :key="key" class="foundation-card"><span>{{ label }}</span><strong>{{ summary[key] }}</strong></article>
    </section>
    <section class="empty-state-panel"><span class="eyebrow">Foundation Ready</span><h2>招聘工作区已建立</h2><p>职位同步、候选人流程和 Windows RPA 任务将在后续阶段接入。</p></section>
  </div>
</template>
```

Create `frontend/src/views/recruitment/RecruitmentPlaceholderView.vue`:

```vue
<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
const route = useRoute()
const title = computed(() => route.meta.title || '招聘管理')
</script>

<template>
  <section class="empty-state-panel">
    <span class="eyebrow">Recruitment Foundation</span>
    <h2>{{ title }}</h2>
    <p>页面入口已建立，业务能力将在下一阶段按已确认的设计逐项接入。</p>
  </section>
</template>
```

- [ ] **Step 4: Add the Copilot entry to the recruitment top bar**

In `AppLayout.vue`, add:

```javascript
import RecruitmentCopilotDrawer from '@/components/RecruitmentCopilotDrawer.vue'
const copilotOpen = ref(false)
```

Render this button only for the recruitment module:

```vue
<button v-if="currentModule === 'recruitment'" class="ghost-button" @click="copilotOpen = true">Copilot</button>
<RecruitmentCopilotDrawer v-if="copilotOpen" @close="copilotOpen = false" />
```

- [ ] **Step 5: Add drawer styles**

Append to `frontend/src/styles.css`:

```css
.drawer-backdrop { position: fixed; inset: 0; z-index: 80; display: flex; justify-content: flex-end; background: rgba(15,23,42,.35); backdrop-filter: blur(2px); }
.copilot-drawer { width: min(520px, 100%); height: 100vh; overflow-y: auto; padding: 26px; background: var(--paper); border-left: 1px solid var(--line); box-shadow: -24px 0 55px rgba(15,23,42,.16); }
.copilot-drawer header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.copilot-drawer h2 { margin: 5px 0 0; color: var(--ink); }
.copilot-drawer > .muted { margin: 0 0 20px; color: var(--muted); font-size: 12px; line-height: 1.7; }
.copilot-drawer .field-label { display: grid; gap: 7px; margin-top: 14px; color: var(--slate); font-size: 11px; font-weight: 700; }
.copilot-actions { display: flex; gap: 9px; margin-top: 20px; }
.copilot-capabilities { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 24px; }
.copilot-capabilities button { min-height: 42px; color: var(--muted); background: #f8fafc; border: 1px solid var(--line); border-radius: 9px; }
.success-note { padding: 10px 12px; color: #0d766d; background: #e5f8f4; border-radius: 8px; font-size: 11px; }
```

- [ ] **Step 6: Run the frontend test suite and production build**

Run from `frontend`:

```powershell
npm test
npm run build
```

Expected: all tests pass and Vite writes the production bundle to `backend/frontend_dist`.

- [ ] **Step 7: Commit the recruitment shell**

```powershell
git add frontend/src
git commit -m "feat: add recruitment shell and copilot settings"
```

Note: `backend/frontend_dist` is ignored and must not be committed. The commit contains only source changes.

### Task 8: Wire remembered login into Vue

**Files:**
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/stores/auth.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Update the auth store signature**

Change the action to:

```javascript
async login(username, password, remember = false) {
  await ensureCsrf()
  this.user = await api('auth/login/', {
    method: 'POST',
    body: JSON.stringify({ username, password, remember }),
  })
  return this.user
}
```

- [ ] **Step 2: Add remember-login UI and HR platform branding**

In `LoginView.vue`, add:

```javascript
const remember = ref(true)
```

Call:

```javascript
await auth.login(username.value, password.value, remember.value)
```

Replace attendance-only copy with:

```vue
<span class="story-kicker">PEOPLE · RECRUITMENT · ATTENDANCE</span>
<h1>招聘与考勤，<br />汇成一套人事系统。</h1>
<p>从候选人到员工档案，再到考勤核算，全流程在统一工作台完成。</p>
```

Change the form title to `登录人事管理系统` and add below the password field:

```vue
<label class="remember-row"><input v-model="remember" type="checkbox" /> <span>记住登录状态</span></label>
```

- [ ] **Step 3: Style the checkbox without changing the visual language**

Add `.remember-row` styles that use the existing text colors and focus ring. The checkbox must retain a visible keyboard focus outline and must not be replaced by a non-semantic element.

- [ ] **Step 4: Run frontend tests and build**

```powershell
npm test
npm run build
```

Expected: tests pass and the login production bundle builds successfully.

- [ ] **Step 5: Commit the login UI**

```powershell
git add frontend/src/views/LoginView.vue frontend/src/stores/auth.js frontend/src/styles.css
git commit -m "feat: add hr platform remembered login ui"
```

### Task 9: Final foundation verification

**Files:**
- Verify: all modified backend and frontend files
- Verify: generated migrations

- [ ] **Step 1: Run Django migration and configuration checks**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe .\backend\manage.py migrate --check
.\.venv\Scripts\python.exe .\backend\manage.py check
```

Expected: no missing migrations and no system-check issues.

- [ ] **Step 2: Run the full backend suite**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test --verbosity 1
```

Expected: attendance, accounts, and recruitment suites all pass.

- [ ] **Step 3: Run the full frontend suite and build**

Run from `frontend`:

```powershell
npm test
npm run build
```

Expected: all Vitest tests pass and the Vite build exits 0.

- [ ] **Step 4: Collect static assets**

Run from the project root:

```powershell
$env:DJANGO_DEBUG='0'
.\.venv\Scripts\python.exe .\backend\manage.py collectstatic --noinput
```

Expected: static assets are copied and post-processed without errors.

- [ ] **Step 5: Perform a Windows HTTP smoke test**

Start Waitress on a temporary port:

```powershell
$env:DJANGO_DEBUG='0'
$python=(Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$backend=(Resolve-Path -LiteralPath '.\backend').Path
$process=Start-Process -FilePath $python -ArgumentList @('-m','waitress','--listen=127.0.0.1:8766','config.wsgi:application') -WorkingDirectory $backend -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
$response=Invoke-WebRequest -Uri 'http://127.0.0.1:8766/login' -UseBasicParsing -TimeoutSec 5
$response.StatusCode
$listener=Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) { Stop-Process -Id $listener.OwningProcess -Force }
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
```

Expected: HTTP 200 and the process is stopped after verification.

- [ ] **Step 6: Verify no third-party recruitment data entered the repository or database**

Run:

```powershell
Get-ChildItem -LiteralPath . -Recurse -File | Where-Object { $_.Name -like 'online-resume-*' -or $_.Name -eq 'candidate_registry.json' -or $_.Name -eq 'resume-score-report.json' }
```

Expected: no output outside the original external ZIP, which is not inside the repository.

- [ ] **Step 7: Record final foundation status**

```powershell
git status --short
git log --oneline -8
```

Expected: only intentionally ignored runtime outputs are absent from Git status and the foundation commits are visible.
