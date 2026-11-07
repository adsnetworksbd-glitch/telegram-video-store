"""
Phase 9 Part 1 — ads infrastructure. Standard library only.
EXECUTED: ad_config (selection / settings / status) and the Monetag provider's
callback verification (real HMAC). STATIC (text/AST): endpoint wiring.
No Firestore, no FastAPI, no ad network, no reward is claimed.
"""
import hashlib, hmac, json, re, sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "video-store-frontend" / "src"
sys.path.insert(0, str(BACKEND))

from app.services.ad_config import (  # noqa: E402
    placement_for, rank_networks, resolve_session_settings, session_status)
from app.services.ad_providers import CallbackRejected, get_provider, provider_types  # noqa: E402

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
read = lambda p: Path(p).read_text(encoding="utf-8")


def net(**kw):
    base = {"is_enabled": True, "type": "monetag", "s2s_callback_supported": True,
            "zone_id": "z", "priority": 1, "placements": {"video_unlock": True, "package_unlock": True}}
    base.update(kw)
    return base


class Selection(unittest.TestCase):
    def test_priority_order_and_fallback(self):
        r = rank_networks([("b", net(priority=2)), ("a", net(priority=1)), ("c", net(priority=2))], "video_unlock")
        self.assertEqual([i for i, _ in r], ["a", "b", "c"])  # a first, rest = fallback order

    def test_disabled_and_non_true_enabled_skipped(self):
        for v in (False, None, "true", 1):
            self.assertEqual(rank_networks([("a", net(is_enabled=v))], "video_unlock"), [])

    def test_unknown_provider_skipped(self):
        self.assertEqual(rank_networks([("a", net(type="nope"))], "video_unlock"), [])

    def test_no_s2s_never_selected(self):
        self.assertEqual(rank_networks([("a", net(s2s_callback_supported=False))], "video_unlock"), [])
        self.assertEqual(rank_networks([("a", net(s2s_callback_supported=None))], "video_unlock"), [])

    def test_missing_zone_skipped(self):
        self.assertEqual(rank_networks([("a", net(zone_id=None))], "video_unlock"), [])

    def test_placement_filtering(self):
        n = net(placements={"video_unlock": True, "package_unlock": False})
        self.assertTrue(rank_networks([("a", n)], "video_unlock"))
        self.assertFalse(rank_networks([("a", n)], "package_unlock"))
        self.assertFalse(rank_networks([("a", n)], "rewarded"))  # not listed → not offered
        self.assertTrue(rank_networks([("a", net(placements=None))], "rewarded"))  # legacy doc: all

    def test_fallback_when_primary_unusable(self):
        r = rank_networks([("a", net(priority=1, zone_id=None)), ("b", net(priority=5))], "video_unlock")
        self.assertEqual([i for i, _ in r], ["b"])

    def test_bad_priority_goes_last(self):
        r = rank_networks([("a", net(priority="x")), ("b", net(priority=9))], "video_unlock")
        self.assertEqual([i for i, _ in r], ["b", "a"])

    def test_placement_for(self):
        self.assertEqual(placement_for("video"), "video_unlock")
        self.assertEqual(placement_for("package"), "package_unlock")


class Settings(unittest.TestCase):
    def test_content_overrides_network(self):
        c = resolve_session_settings(
            {"default_ads_required": 5, "unlock_duration_hours": 48, "session_timeout_minutes": 10},
            {"ads_required": 2, "ads_unlock_duration_hours": 12})
        self.assertEqual(c, {"ads_required": 2, "unlock_hours": 12, "timeout_minutes": 10})

    def test_network_defaults_and_hard_defaults(self):
        self.assertEqual(resolve_session_settings({"default_ads_required": 4, "unlock_duration_hours": 6}, {}),
                         {"ads_required": 4, "unlock_hours": 6, "timeout_minutes": 30})
        self.assertEqual(resolve_session_settings({}, {}), {"ads_required": 3, "unlock_hours": 24, "timeout_minutes": 30})

    def test_garbage_is_clamped_not_trusted(self):
        c = resolve_session_settings({"session_timeout_minutes": 99999}, {"ads_required": 0, "ads_unlock_duration_hours": -5})
        self.assertEqual(c["timeout_minutes"], 240)
        self.assertEqual(c["ads_required"], 1)   # never 0 ads → instant unlock
        self.assertEqual(c["unlock_hours"], 0)   # negative cannot create an already-expired grant
        self.assertEqual(resolve_session_settings({}, {"ads_required": True})["ads_required"], 3)


class Status(unittest.TestCase):
    def test_states(self):
        f = timedelta(minutes=5)
        self.assertEqual(session_status({"expires_at": NOW + f}, NOW), "pending")
        self.assertEqual(session_status({"expires_at": NOW + f, "s2s_verified_count": 1}, NOW), "in_progress")
        self.assertEqual(session_status({"expires_at": NOW - f}, NOW), "expired")
        self.assertEqual(session_status({"expires_at": NOW - f, "is_complete": True}, NOW), "completed")
        self.assertEqual(session_status({}, NOW), "pending")


class MonetagProvider(unittest.TestCase):
    P = get_provider("monetag")
    SECRET = "s3cret"

    def sign(self, body: bytes, secret=None):
        return hmac.new((secret or self.SECRET).encode(), body, hashlib.sha256).hexdigest()

    def call(self, payload, secret=SECRET, sig=None, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        return self.P.verify_callback(secret, {"X-Monetag-Signature": sig if sig is not None else self.sign(body)}, body)

    def test_registry(self):
        self.assertEqual(provider_types(), ["monetag"])
        self.assertIsNone(get_provider("nope")); self.assertIsNone(get_provider(None))
        self.assertTrue(self.P.supports_s2s)

    def test_valid_callback(self):
        e = self.call({"session_id": "S1", "ad_id": "A1"})
        self.assertEqual((e.session_id, e.ad_id), ("S1", "A1"))
        e = self.call({"custom_data": {"session_id": "S2"}, "transaction_id": 77})
        self.assertEqual((e.session_id, e.ad_id), ("S2", "77"))

    def test_bad_signature_rejected_403(self):
        for kw in ({"sig": "0" * 64}, {"sig": ""}, {"secret": "other"}, {"secret": ""}):
            with self.assertRaises(CallbackRejected) as c:
                self.call({"session_id": "S1", "ad_id": "A"}, **kw)
            self.assertEqual(c.exception.status, 403)

    def test_unconfigured_secret_fails_closed_even_with_matching_empty_hmac(self):
        body = b'{"session_id":"S","ad_id":"A"}'
        with self.assertRaises(CallbackRejected):
            self.P.verify_callback("", {"X-Monetag-Signature": self.sign(body, "")}, body)

    def test_malformed_payloads_never_crash(self):
        for raw in (b"not json", b"[]", b'"x"', b"null", b'{"custom_data": 5}', b'{"session_id": {"a":1}}',
                    b'{"session_id": "a/b"}', b'{"session_id": ""}'):
            try:
                self.call(None, raw=raw)
                self.fail(f"accepted {raw!r}")
            except CallbackRejected as e:
                self.assertIn(e.status, (200, 400))

    def test_odd_ad_id_types_become_none(self):
        for v in ([1], {"a": 1}, True):
            self.assertIsNone(self.call({"session_id": "S", "ad_id": v}).ad_id)

    def test_no_secret_in_public_config(self):
        cfg = self.P.public_config("m", {"zone_id": "z", "sdk_url": "https://x/y.js", "s2s_callback_secret_ref": "MONETAG_CALLBACK_SECRET",
                                          "secret": "leak", "api_key": "leak"})
        self.assertEqual(set(cfg), {"network_id", "provider_id", "zone_id", "type", "sdk_url"})
        self.assertIsNone(self.P.public_config("m", {"sdk_url": "http://insecure"})["sdk_url"])

    def test_config_problems(self):
        self.assertTrue(self.P.config_problems({"zone_id": None}))
        self.assertEqual(self.P.config_problems({"zone_id": "1"}), [])


class Wiring(unittest.TestCase):
    ads = read(BACKEND / "app/api/v1/endpoints/ads.py")
    admin = read(BACKEND / "app/api/v1/endpoints/admin.py")

    def test_routes_and_legacy_url_kept(self):
        for r in ('"/ads/session/start"', '"/ads/session/complete"', '"/webhooks/monetag"', '"/webhooks/ads/{provider_type}"'):
            self.assertIn(r, self.ads)

    def test_user_endpoints_require_jwt_and_use_token_identity(self):
        self.assertEqual(self.ads.count("Depends(get_current_user)"), 2)
        self.assertNotIn("body.user_id", self.ads)

    def test_access_only_from_provider_verified_callback(self):
        # Part 2: the single create_entitlement lives in _finalize_grant, which is
        # only called after provider.verify_callback (callback) or for a
        # provider-verified grant_pending session (poll recovery).
        self.assertEqual(self.ads.count("create_entitlement("), 1)
        cb = self.ads[self.ads.index("async def _handle_provider_callback"):]
        self.assertLess(cb.index("provider.verify_callback("), cb.index("_finalize_grant("))

    def test_callback_guards(self):
        cfg = read(BACKEND / "app/services/ad_config.py")
        for needle in ("already_complete", "duplicate", "session expired"):
            self.assertIn(needle, cfg)            # idempotency core (executed in Part 2 tests)
        for needle in ("provider mismatch", "no ad_id"):
            self.assertIn(needle, self.ads)
        cb = self.ads[self.ads.index("async def _handle_provider_callback"):]
        claim = cb.index("_claim_ad(")
        for cond in ('if (s0.get("provider_id") or "monetag") != provider.type:', "if not ad_id:"):
            self.assertIn(cond, cb)
            self.assertLess(cb.index(cond), claim, cond)

    def test_ads_session_uses_ranked_network_and_resolved_settings(self):
        for needle in ("rank_networks(", "resolve_session_settings(", 'cfg["timeout_minutes"]',
                       '"unlock_duration_hours": cfg["unlock_hours"]', '"placement": placement'):
            self.assertIn(needle, self.ads)
        self.assertNotIn(".order_by(\"priority\")", self.ads)   # no new composite-index dependency

    def test_admin_ad_endpoints_protected(self):
        for fn in ("list_ad_networks", "upsert_ad_network"):
            m = re.search(rf"async def {fn}\((.*?)\):", self.admin, re.S)
            self.assertIn("Depends(get_current_admin)", m.group(1))

    def test_admin_cannot_set_secrets_or_s2s_flag(self):
        m = re.search(r"class AdNetworkUpdate\(BaseModel\):(.*?)\ndef _ad_network_view", self.admin, re.S).group(1)
        for bad in ("secret", "api_key", "token", "s2s_callback"):
            self.assertNotIn(bad, m.split("@field_validator")[0].lower())
        self.assertIn("provider.supports_s2s", self.admin)
        self.assertIn("provider.secret_setting", self.admin)
        self.assertIn("sdk_url must start with https://", self.admin)
        self.assertIn("merge=True", self.admin)   # never overwrites a document
        self.assertIn('changes.setdefault("is_enabled", False)', self.admin)  # new network starts disabled
        self.assertIn("ad_network_updated", self.admin)  # audited

    def test_no_deletes_of_ad_data(self):
        self.assertNotIn(".delete(", self.ads); self.assertNotIn("AD_NETWORKS).document(network_id).delete", self.admin)

    def test_schema_changes_are_additive(self):
        s = read(BACKEND / "app/schemas/__init__.py")
        self.assertRegex(s, r"provider_id: str \| None = None")
        self.assertRegex(s, r"status: str \| None = None")

    def test_no_secret_names_or_values_in_frontend(self):
        for f in FRONT.rglob("*.ts*"):
            t = read(f)
            self.assertNotIn("MONETAG_CALLBACK_SECRET", t, f)
            self.assertNotRegex(t, r"X-Monetag-Signature", f)

    def test_frontend_never_grants_from_ad_sdk(self):
        t = read(FRONT / "pages/WatchAds/index.tsx")
        self.assertIn("setAwaiting", t)
        # unlocked only from the backend poll or a backend access check
        self.assertEqual(t.count("setScreen('unlocked')"), 2)
        self.assertNotIn("outcome === 'shown'" + ") { setScreen('unlocked')", t)

    def test_nav_lock_wired(self):
        t = read(FRONT / "pages/WatchAds/index.tsx")
        self.assertIn("useAdNavigationLock(adPhase === 'loading' || adPhase === 'showing')", t)


if __name__ == "__main__":
    unittest.main()
