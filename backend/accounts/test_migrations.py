from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RepairPartialModelProfilesMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0003_expand_model_api_urls")
    migrate_to = ("accounts", "0005_clear_legacy_model_key_hints")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        user_model = old_apps.get_model("auth", "User")
        credential_model = old_apps.get_model("accounts", "UserModelCredential")
        profile_model = old_apps.get_model("accounts", "UserModelProfile")

        complete_user = user_model.objects.create(username="migration-complete")
        credential_model.objects.create(
            user_id=complete_user.pk,
            api_url="https://stale.example/v1",
            model="stale-model",
            encrypted_api_key="encrypted-stale",
            key_last4="tale",
        )
        profile_model.objects.create(
            user_id=complete_user.pk,
            name="完整配置",
            api_url="https://models.example/v1",
            model="complete-model",
            encrypted_api_key="encrypted-complete",
            key_last4="lete",
            is_active=True,
        )

        partial_user = user_model.objects.create(username="migration-partial")
        credential_model.objects.create(
            user_id=partial_user.pk,
            api_url="https://partial.example/v1",
            model="",
            encrypted_api_key="",
        )
        profile_model.objects.create(
            user_id=partial_user.pk,
            name="部分配置",
            api_url="https://partial.example/v1",
            model="",
            encrypted_api_key="",
            is_active=True,
        )

        empty_user = user_model.objects.create(username="migration-empty")
        credential_model.objects.create(user_id=empty_user.pk)
        self.complete_user_id = complete_user.pk
        self.partial_user_id = partial_user.pk
        self.empty_user_id = empty_user.pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_complete_projection_is_repaired_and_partial_or_empty_current_state_is_removed(self):
        credential_model = self.apps.get_model("accounts", "UserModelCredential")
        profile_model = self.apps.get_model("accounts", "UserModelProfile")

        complete_profile = profile_model.objects.get(user_id=self.complete_user_id)
        complete_credential = credential_model.objects.get(user_id=self.complete_user_id)
        self.assertTrue(complete_profile.is_active)
        self.assertEqual(complete_credential.api_url, complete_profile.api_url)
        self.assertEqual(complete_credential.model, complete_profile.model)
        self.assertEqual(complete_credential.encrypted_api_key, complete_profile.encrypted_api_key)
        self.assertEqual(complete_profile.key_last4, "")
        self.assertEqual(complete_credential.key_last4, "")

        partial_profile = profile_model.objects.get(user_id=self.partial_user_id)
        self.assertFalse(partial_profile.is_active)
        self.assertFalse(credential_model.objects.filter(user_id=self.partial_user_id).exists())
        self.assertFalse(credential_model.objects.filter(user_id=self.empty_user_id).exists())
