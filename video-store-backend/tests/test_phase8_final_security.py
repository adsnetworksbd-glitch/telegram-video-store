"""Phase 8 final: static checks for security fixes (no Firestore / network)."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class FinalSecurity(unittest.TestCase):
    def test_firestore_rules_deny_all_clients(self):
        rules = read("firestore.rules")
        self.assertIn("allow read, write: if false;", rules)
        self.assertNotIn("if true", rules)
        self.assertEqual(json.loads(read("firebase.json"))["firestore"]["rules"], "firestore.rules")

    def test_webhook_rejects_non_object_payload_and_bad_custom_data(self):
        # Phase 9: payload parsing moved into the provider module
        s = read("app/services/ad_providers/monetag.py")
        self.assertIn("isinstance(payload, dict)", s)
        self.assertIn("isinstance(custom, dict)", s)
        self.assertNotIn('payload.get("custom_data", {})', s)

    def test_server_token_compare_is_bytes(self):
        s = read("app/api/v1/endpoints/ads.py")
        self.assertIn("body.server_token.encode()", s)

    def test_admin_token_requires_exp(self):
        s = read("app/core/security.py")
        self.assertEqual(s.count('"require_exp": True'), 2)
