from django.test import SimpleTestCase

from recruitment.rpa.capabilities import REGISTRY, capability_payload


class CapabilityRegistryTests(SimpleTestCase):
    def test_sync_positions_is_read_only_and_cli_backed(self):
        spec = REGISTRY["sync_positions"]

        self.assertTrue(spec.read_only)
        self.assertFalse(spec.requires_approval)
        self.assertEqual(spec.adapter, "cli")
        self.assertTrue(spec.enabled)

    def test_write_actions_are_enabled_only_with_approval(self):
        spec = REGISTRY["greet"]

        self.assertTrue(spec.enabled)
        self.assertTrue(spec.requires_approval)
        self.assertFalse(spec.read_only)

    def test_heartbeat_payload_is_json_safe(self):
        payload = capability_payload()

        self.assertEqual(payload["sync_positions"]["adapter"], "cli")
        self.assertEqual(payload["greet"]["consumes"], "contact")
