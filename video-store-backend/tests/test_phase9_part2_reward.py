"""
Phase 9 Part 2 — reward verification & unlock. Standard library only.
EXECUTED: Monetag GET-postback verification, decide_callback (idempotency core,
replayed through a tiny in-memory session), log redaction, access_rules with ads
entitlements. STATIC: endpoint wiring (transaction, deterministic ids, ownership).
No Firestore / FastAPI / Monetag / reward is simulated as real.
"""
import re, sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.ad_config import decide_callback  # noqa: E402
from app.services.ad_providers import CallbackRejected, get_provider  # noqa: E402
from app.services.access_rules import evaluate_access  # noqa: E402
from app.core.log_redact import redact_secrets  # noqa: E402
from app.core.rate_limit import match_rule  # noqa: E402

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
SID = "123e4567-e89b-12d3-a456-426614174000"
SECRET = "long-random-secret-value"
P = get_provider("monetag")
read = lambda p: (BACKEND / p).read_text(encoding="utf-8")


def q(**kw):
    base = {"secret": SECRET, "ymid": f"{SID}.abc123def456", "event_type": "impression",
            "reward_event_type": "valued", "zone_id": "555", "telegram_id": "42"}
    base.update({k: v for k, v in kw.items() if v is not None})
    return {k: v for k, v in base.items() if not (k in kw and kw[k] is None)}


def verify(query):
    return P.verify_callback(SECRET, {}, b"", query)


class MonetagGetPostback(unittest.TestCase):
    def test_valid_valued_impression(self):
        e = verify(q())
        self.assertEqual((e.session_id, e.ad_id, e.telegram_id, e.zone_id), (SID, f"{SID}.abc123def456", "42", "555"))

    def test_wrong_or_missing_secret_is_403_and_generic(self):
        for bad in ("nope", "", None):
            with self.assertRaises(CallbackRejected) as c:
                verify(q(secret=bad))
            self.assertEqual((c.exception.status, c.exception.detail), (403, "Invalid callback"))
        with self.assertRaises(CallbackRejected) as c:   # alt param name `key` works, wrong value fails
            verify({**q(secret=None), "key": "x"})
        self.assertEqual(c.exception.status, 403)

    def test_unconfigured_secret_fails_closed(self):
        with self.assertRaises(CallbackRejected) as c:
            P.verify_callback("", {}, b"", q(secret=""))
        self.assertEqual(c.exception.status, 403)

    def test_only_impression_valued_counts(self):
        for kw in ({"event_type": "click"}, {"event_type": ""}, {"reward_event_type": "not_valued"},
                   {"reward_event_type": ""}, {"reward_event_type": "non_valued"}):
            with self.assertRaises(CallbackRejected) as c:
                verify(q(**kw))
            self.assertEqual(c.exception.status, 200, kw)   # acknowledged, never counted

    def test_bad_ymid_never_counts_and_never_crashes(self):
        for y in ("", "not-a-session", f"{SID}.", f"{SID}.a b", "../etc/passwd", "x" * 500, f"{SID}.{'z'*80}"):
            with self.assertRaises(CallbackRejected) as c:
                verify(q(ymid=y))
            self.assertEqual(c.exception.status, 200, y)

    def test_telegram_id_optional_and_numeric_only(self):
        self.assertIsNone(verify(q(telegram_id="")).telegram_id)
        self.assertIsNone(verify(q(telegram_id="abc")).telegram_id)

    def test_secret_compare_non_ascii_does_not_crash(self):
        with self.assertRaises(CallbackRejected) as c:
            verify(q(secret="ü" * 10))
        self.assertEqual(c.exception.status, 403)

    def test_legacy_post_hmac_still_works_and_get_params_dont_bypass_it(self):
        import hashlib, hmac, json
        body = json.dumps({"session_id": "S1", "ad_id": "A1"}).encode()
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(P.verify_callback(SECRET, {"X-Monetag-Signature": sig}, body).ad_id, "A1")
        with self.assertRaises(CallbackRejected):
            P.verify_callback(SECRET, {}, body)          # no signature
        with self.assertRaises(CallbackRejected):
            P.verify_callback(SECRET, {}, b"", {})       # empty everything


class IdempotencyCore(unittest.TestCase):
    def session(self, **kw):
        s = {"ads_required": 3, "s2s_verified_count": 0, "completed_ad_ids": [], "is_complete": False,
             "expires_at": NOW + timedelta(minutes=30)}
        s.update(kw)
        return s

    def apply(self, s, ad_id, now=NOW):
        r, upd, grant = decide_callback(s, ad_id, now)
        if upd:
            s.update(upd)
        return r["status"], grant

    def test_exactly_required_ads_then_one_grant(self):
        s = self.session(); grants = 0
        for i in range(3):
            st, g = self.apply(s, f"ad{i}")
            self.assertEqual(st, "ok"); grants += g
        self.assertEqual((s["s2s_verified_count"], grants, s["grant_pending"]), (3, 1, True))

    def test_replay_of_same_ad_never_double_counts(self):
        s = self.session()
        self.assertEqual(self.apply(s, "ad1")[0], "ok")
        for _ in range(5):
            self.assertEqual(self.apply(s, "ad1")[0], "duplicate")
        self.assertEqual(s["s2s_verified_count"], 1)

    def test_replay_cannot_reach_threshold(self):
        s = self.session()
        for _ in range(10):
            self.apply(s, "same")
        self.assertEqual(s["s2s_verified_count"], 1)
        self.assertFalse(s.get("grant_pending"))

    def test_extra_ads_after_threshold_not_counted(self):
        s = self.session(ads_required=1)
        self.assertEqual(self.apply(s, "a"), ("ok", True))
        st, grant = self.apply(s, "b")                      # grant still pending → retry finalize, no new count
        self.assertEqual((st, grant, s["s2s_verified_count"]), ("already_complete", True, 1))

    def test_complete_session_ignores_everything(self):
        s = self.session(is_complete=True, s2s_verified_count=3)
        self.assertEqual(decide_callback(s, "new", NOW), ({"status": "already_complete"}, None, False))

    def test_expired_session_rejected_and_marked(self):
        s = self.session(expires_at=NOW - timedelta(seconds=1))
        r, upd, grant = decide_callback(s, "a", NOW)
        self.assertEqual((r["status"], grant, upd["status"]), ("ignored", False, "expired"))
        self.assertNotIn("s2s_verified_count", upd)

    def test_expired_but_threshold_reached_may_finish(self):
        s = self.session(expires_at=NOW - timedelta(minutes=1), s2s_verified_count=3, grant_pending=True,
                         completed_ad_ids=["a", "b", "c"])
        self.assertTrue(decide_callback(s, "a", NOW)[2])

    def test_garbage_state_is_safe(self):
        r, upd, grant = decide_callback({"ads_required": "x", "s2s_verified_count": None, "completed_ad_ids": None}, "a", NOW)
        self.assertEqual(r["status"], "ok"); self.assertFalse(grant)   # default 3 required, 1 counted


class AccessIntegration(unittest.TestCase):
    def ent(self, src, *, hours=None, life=False, status="active"):
        return {"access_source": src, "is_lifetime": life, "status": status,
                "expires_at": None if life else NOW + timedelta(hours=hours)}

    def test_ads_is_its_own_source(self):
        a = evaluate_access([self.ent("ads_unlock", hours=24)], NOW)
        self.assertEqual((a["granted"], a["source"]), (True, "ads_unlock"))
        self.assertEqual(a["active_sources"], ["ads_unlock"])

    def test_paid_and_lifetime_survive_and_win(self):
        a = evaluate_access([self.ent("ads_unlock", hours=24), self.ent("individual_purchase", life=True)], NOW)
        self.assertEqual((a["source"], a["is_lifetime"]), ("individual_purchase", True))
        self.assertIn("ads_unlock", a["active_sources"])

    def test_expired_ads_never_valid_again_but_others_stay(self):
        old = {"access_source": "ads_unlock", "is_lifetime": False, "status": "active", "expires_at": NOW - timedelta(seconds=1)}
        self.assertFalse(evaluate_access([old], NOW)["granted"])
        a = evaluate_access([old, self.ent("package_purchase", hours=48)], NOW)
        self.assertEqual((a["granted"], a["source"]), (True, "package_purchase"))

    def test_ads_without_expiry_fails_closed(self):
        bad = {"access_source": "ads_unlock", "is_lifetime": False, "status": "active", "expires_at": None}
        self.assertFalse(evaluate_access([bad], NOW)["granted"])


class Redaction(unittest.TestCase):
    def test_secret_query_params_are_scrubbed(self):
        line = f'GET /api/v1/webhooks/monetag?secret={SECRET}&ymid={SID}.ab&key=k1&token=t2 HTTP/1.1'
        out = redact_secrets(line)
        for leaked in (SECRET, "k1", "t2"):
            self.assertNotIn(leaked, out)
        self.assertIn(SID, out)                      # non-secret params untouched

    def test_filter_wired_in_main(self):
        m = read("app/main.py")
        self.assertIn('"uvicorn.access"', m); self.assertIn("RedactSecretsFilter", m)


class Wiring(unittest.TestCase):
    ads = read("app/api/v1/endpoints/ads.py")

    def test_get_and_post_routes(self):
        for r in ('@router.get("/webhooks/monetag")', '@router.post("/webhooks/monetag")',
                  '@router.get("/webhooks/ads/{provider_type}")'):
            self.assertIn(r, self.ads)

    def test_counting_is_transactional(self):
        self.assertIn("@async_transactional", self.ads)
        self.assertIn("transaction.update(session_ref, update)", self.ads)
        self.assertIn("await _claim_ad(db.transaction(), session_ref, ad_id, now)", self.ads)
        self.assertNotIn("new_count = s.get", self.ads)       # old read-then-write path is gone

    def test_unlock_is_idempotent_and_deterministic(self):
        self.assertIn('ent_id = f"ent_ads_{session_id}"', self.ads)
        self.assertIn("entitlement_id=ent_id", self.ads)
        self.assertRegex(self.ads, r"except AlreadyExists:\n\s+created = False")   # a repeat is a no-op, not an error
        self.assertIn('tx_id=f"ads_{session_id}"', self.ads)
        self.assertEqual(self.ads.count("create_entitlement("), 1)

    def test_unlock_only_after_verified_callback_or_backend_state(self):
        self.assertEqual(self.ads.count("_finalize_grant("), 3)   # def + callback + recovery
        cb = self.ads[self.ads.index("async def _handle_provider_callback"):]
        self.assertLess(cb.index("provider.verify_callback("), cb.index("_finalize_grant("))
        # polling endpoint recovers ONLY a grant the provider already verified
        poll = self.ads[self.ads.index("async def check_ad_session"):self.ads.index('@router.get("/webhooks/monetag")')]
        self.assertIn('s.get("grant_pending")', poll)
        self.assertNotIn("body.is_complete", poll)

    def test_session_marked_complete_only_at_the_end_of_finalize(self):
        f = self.ads[self.ads.index("async def _finalize_grant"):self.ads.index("async def _handle_provider_callback")]
        self.assertLess(f.index("create_entitlement("), f.index('"is_complete": True'))
        self.assertLess(f.index("record_transaction("), f.index('"is_complete": True'))
        self.assertIn('action="ads_unlock_granted"', f)

    def test_ownership_and_zone_checks(self):
        for n in ('event.telegram_id != str(s0.get("user_id"))', "zone mismatch", "provider mismatch"):
            self.assertIn(n, self.ads)
        self.assertIn('s.get("user_id") != user_id', self.ads)   # poll: owner only
        self.assertIn("hmac.compare_digest", self.ads)            # server_token

    def test_errors_are_generic(self):
        self.assertIn('"Invalid callback" if e.status == 403', self.ads)
        self.assertNotIn("str(e)", self.ads)

    def test_webhook_rate_limit_covers_get(self):
        self.assertIsNotNone(match_rule("/api/v1/webhooks/monetag", "GET"))
        self.assertEqual(match_rule("/api/v1/webhooks/monetag", "GET")[:2], (600, 60))
        self.assertEqual(match_rule("/api/v1/ads/session/start", "POST")[:2], (30, 60))

    def test_ledger_helper_backward_compatible(self):
        t = read("app/services/transaction.py")
        self.assertIn("tx_id: str | None = None", t)

    def test_frontend_has_no_secret_and_unique_ymid(self):
        fe = (BACKEND.parent / "video-store-frontend/src")
        r = (fe / "utils/rewardedAd.ts").read_text()
        self.assertIn("makeYmid(sessionId)", r)
        for f in fe.rglob("*.ts*"):
            self.assertNotIn("MONETAG_CALLBACK_SECRET", f.read_text())


if __name__ == "__main__":
    unittest.main()
