"""
Phase 10 Part 2A — verification flow, history, duplicate protection, admin hooks.

OFFLINE. No Binance, no Firestore. What this proves and what it does not:
  * the decision rules, the orchestration (against an in-memory fake database),
    the RSA signature check (against a locally generated key pair) and the
    source-level security contract are tested;
  * NOT tested: a real Binance response, Binance's real webhook certificate /
    signature format, real Firestore transactions.
"""
import asyncio
import base64
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import payment_methods as pm  # noqa: E402
from app.services import payment_verification as pv  # noqa: E402

SRC = lambda *p: (BACKEND / "app" / Path(*p)).read_text()  # noqa: E731
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def order(**kw):
    d = {"_id": "o1", "status": "awaiting_payment", "final_usdt": 10.0, "user_id": "u1"}
    d.update(kw)
    return d


def payment(**kw):
    d = {"verification_method": pv.VERIFY_AUTO, "binance_prepay_id": "pp1", "verification_status": "pending"}
    d.update(kw)
    return d


def bn(**kw):
    d = {"status": "PAID", "currency": "USDT", "orderAmount": "10.00000000", "merchantTradeNo": "o1", "prepayId": "pp1"}
    d.update(kw)
    return d


# ─── Pure decision rules ──────────────────────────────────────────────────────
class Decision(unittest.TestCase):
    def test_exact_paid_auto_fulfills(self):
        o = pv.decide_binance_outcome(order(), payment(), bn())
        self.assertEqual((o.action, o.paid_usdt), ("fulfill", 10.0))

    def test_overpaid_still_fulfills(self):
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(orderAmount="10.5")).action, "fulfill")

    def test_underpaid_goes_to_review_never_access(self):
        o = pv.decide_binance_outcome(order(), payment(), bn(orderAmount="9.99"))
        self.assertEqual(o.action, "review")

    def test_wrong_currency_review(self):
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(currency="BUSD")).action, "review")

    def test_answer_for_other_order_review(self):
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(merchantTradeNo="other")).action, "review")
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(prepayId="zzz")).action, "review")

    def test_unreadable_amount_review(self):
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(orderAmount=None)).action, "review")

    def test_manual_mode_never_auto_grants(self):
        o = pv.decide_binance_outcome(order(), payment(verification_method=pv.VERIFY_MANUAL), bn())
        self.assertEqual((o.action, o.reason), ("review", "binance_paid_manual_mode"))

    def test_rejected_order_paid_later_goes_to_admin(self):
        self.assertEqual(pv.decide_binance_outcome(order(status="failed"), payment(), bn()).action, "review")

    def test_late_payment_on_expired_order_is_honoured(self):
        self.assertEqual(pv.decide_binance_outcome(order(status="expired"), payment(), bn()).action, "fulfill")

    def test_pending_and_unknown_wait(self):
        for st in ("INITIAL", "PENDING", "", "REFUNDING", "SOMETHING_NEW"):
            self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(status=st)).action, "wait", st)

    def test_canceled_expired_close_open_order_only(self):
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(status="EXPIRED")).order_status, "expired")
        self.assertEqual(pv.decide_binance_outcome(order(), payment(), bn(status="CANCELED")).order_status, "failed")
        self.assertEqual(pv.decide_binance_outcome(order(status="under_review"), payment(), bn(status="CANCELED")).action, "noop")

    def test_completed_and_refunded_are_noop(self):
        self.assertEqual(pv.decide_binance_outcome(order(status="completed"), payment(), bn()).action, "noop")
        self.assertEqual(pv.decide_binance_outcome(order(status="refunded"), payment(), bn()).action, "noop")


class SmallHelpers(unittest.TestCase):
    def test_wait_seconds(self):
        self.assertEqual(pv.verify_wait_seconds({}, NOW, 5), 0)
        self.assertEqual(pv.verify_wait_seconds({"last_checked_at": NOW - timedelta(seconds=2)}, NOW, 5), 3)
        self.assertEqual(pv.verify_wait_seconds({"last_checked_at": NOW - timedelta(seconds=9)}, NOW, 5), 0)
        self.assertEqual(pv.verify_wait_seconds({"last_checked_at": NOW}, NOW, 0), 0)

    def test_retry_limit(self):
        self.assertTrue(pv.retry_limit_reached(5, 5))
        self.assertFalse(pv.retry_limit_reached(4, 5))
        self.assertFalse(pv.retry_limit_reached(99, 0))   # 0 = no cap

    def test_history_event_shape(self):
        e = pv.history_event("awaiting_payment", "under_review", "u1", "user_submit", "x", NOW)
        self.assertEqual((e["from"], e["to"], e["by"], e["source"], e["at"]), ("awaiting_payment", "under_review", "u1", "user_submit", NOW))

    def test_claim_id_deterministic_and_distinct(self):
        self.assertEqual(pv.txhash_claim_id("0xaa"), pv.txhash_claim_id("0xaa"))
        self.assertNotEqual(pv.txhash_claim_id("0xaa"), pv.txhash_claim_id("0xab"))


class TxHashRules(unittest.TestCase):
    H = "ab" * 32

    def test_same_hash_one_spelling(self):
        a = pm.normalize_txhash("usdt_bep20", self.H.upper())
        b = pm.normalize_txhash("usdt_bep20", "0x" + self.H)
        self.assertEqual(a, b)

    def test_network_shapes(self):
        self.assertIsNone(pm.txhash_problem("usdt_trc20", self.H))
        self.assertTrue(pm.txhash_problem("usdt_trc20", "0x" + self.H))
        self.assertIsNone(pm.txhash_problem("usdt_erc20", self.H))        # 0x added
        self.assertTrue(pm.txhash_problem("usdt_erc20", "12345678"))
        self.assertIsNone(pm.txhash_problem("binance_id", "ORDER12345"))  # free-form reference

    def test_only_gateway_can_be_auto(self):
        trc = "T" + "A" * 33
        m = pm.normalize_method("w", {"type": "usdt_trc20", "is_enabled": True, "wallet_address": trc,
                                      "auto_verification_supported": True})
        self.assertFalse(m["auto_verification_supported"])
        self.assertTrue(pm.config_problems({"name": "x", "type": "usdt_trc20", "wallet_address": trc,
                                            "auto_verification_supported": True}))

    def test_admin_may_switch_binance_pay_to_manual(self):
        self.assertEqual(pm.config_problems({"name": "BP", "type": "binance_pay",
                                             "auto_verification_supported": False, "manual_review_supported": True}), [])
        self.assertTrue(pm.config_problems({"name": "BP", "type": "binance_pay",
                                            "auto_verification_supported": False, "manual_review_supported": False}))


# ─── Binance RSA webhook signature (real crypto, local key pair) ──────────────
def _load_real_binance():
    saved = {k: sys.modules.get(k) for k in ("httpx", "app.core.config")}
    sys.modules["httpx"] = types.ModuleType("httpx")
    cfg = types.ModuleType("app.core.config")
    cfg.settings = types.SimpleNamespace(
        BINANCE_PAY_BASE_URL="https://x", BINANCE_PAY_API_SECRET="s3cret", BINANCE_PAY_API_KEY="k")
    sys.modules["app.core.config"] = cfg
    try:
        spec = importlib.util.spec_from_file_location("binance_real", BACKEND / "app" / "services" / "binance.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class WebhookSignature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        cls.b = _load_real_binance()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pub = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        payload = b"1700000000000\nnonce123\n{\"a\":1}\n"
        cls.sig = base64.b64encode(key.sign(payload, padding.PKCS1v15(), hashes.SHA256())).decode()

    def test_valid_signature(self):
        self.assertTrue(self.b.verify_rsa_signature(self.pub, '{"a":1}', "1700000000000", "nonce123", self.sig))

    def test_tampered_body_rejected(self):
        self.assertFalse(self.b.verify_rsa_signature(self.pub, '{"a":2}', "1700000000000", "nonce123", self.sig))

    def test_wrong_nonce_or_garbage_rejected(self):
        self.assertFalse(self.b.verify_rsa_signature(self.pub, '{"a":1}', "1700000000000", "other", self.sig))
        self.assertFalse(self.b.verify_rsa_signature(self.pub, '{"a":1}', "1", "n", "not-base64!!"))
        self.assertFalse(self.b.verify_rsa_signature("not a key", '{"a":1}', "1", "n", self.sig))


# ─── Orchestration against an in-memory fake Firestore ────────────────────────
class _Snap:
    def __init__(self, ref, data):
        self.reference, self.id, self._d = ref, ref.id, data
        self.exists = data is not None

    def to_dict(self):
        return None if self._d is None else dict(self._d)


class _Ref:
    def __init__(self, db, col, id_):
        self.db, self.col, self.id = db, col, id_

    @property
    def _store(self):
        return self.db.data.setdefault(self.col, {})

    async def get(self, **_kw):
        return _Snap(self, self._store.get(self.id))

    async def update(self, data):
        _apply(self._store[self.id], data)

    async def create(self, data):
        if self.id in self._store:
            raise _AlreadyExists()
        self._store[self.id] = dict(data)

    async def set(self, data):
        self._store[self.id] = dict(data)


class _Query:
    def __init__(self, db, col, conds):
        self.db, self.col, self.conds = db, col, conds

    def where(self, filter):
        return _Query(self.db, self.col, self.conds + [filter])

    def limit(self, n):
        return self

    async def stream(self):
        for id_, d in list(self.db.data.get(self.col, {}).items()):
            if all(d.get(f.field) == f.value for f in self.conds):
                yield _Snap(_Ref(self.db, self.col, id_), d)


class _Coll(_Query):
    def __init__(self, db, col):
        super().__init__(db, col, [])

    def document(self, id_):
        return _Ref(self.db, self.col, id_)


class _Txn:
    def update(self, ref, data):
        _apply(ref._store[ref.id], data)


class FakeDB:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return _Coll(self, name)

    def transaction(self):
        return _Txn()


class _ArrayUnion:
    def __init__(self, items):
        self.items = items


class _Increment:
    def __init__(self, n):
        self.n = n


class _AlreadyExists(Exception):
    pass


def _apply(doc, data):
    for k, v in data.items():
        if isinstance(v, _ArrayUnion):
            doc.setdefault(k, [])
            doc[k] = doc[k] + [i for i in v.items if i not in doc[k]]
        elif isinstance(v, _Increment):
            doc[k] = (doc.get(k) or 0) + v.n
        else:
            doc[k] = v


class _FF:
    def __init__(self, field, op, value):
        self.field, self.op, self.value = field, op, value


class BinanceUnavailable(RuntimeError):
    pass


_STUBBED = ["google", "google.cloud", "google.cloud.firestore_v1", "google.cloud.firestore_v1.async_transaction",
            "google.cloud.firestore_v1.base_query", "google.api_core", "google.api_core.exceptions",
            "app.db.firebase", "app.services.binance", "app.services.fulfillment", "app.utils.audit"]
_SAVED: dict = {}
STATE: dict = {}


def setUpModule():
    for k in _STUBBED:
        _SAVED[k] = sys.modules.get(k)

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    def async_transactional(fn):
        async def wrapper(txn):
            return await fn(txn)
        return wrapper

    mod("google"); mod("google.cloud")
    mod("google.cloud.firestore_v1", ArrayUnion=_ArrayUnion, Increment=_Increment)
    mod("google.cloud.firestore_v1.async_transaction", async_transactional=async_transactional)
    mod("google.cloud.firestore_v1.base_query", FieldFilter=_FF)
    mod("google.api_core"); mod("google.api_core.exceptions", AlreadyExists=_AlreadyExists)
    mod("app.db.firebase", Col=types.SimpleNamespace(ORDERS="orders", PAYMENTS="payments", APP_SETTINGS="app_settings"))

    async def audit_log(**kw):
        STATE.setdefault("audit", []).append(kw["action"])

    mod("app.utils.audit", audit_log=audit_log)

    async def query_order(order_id):
        STATE["queried"] = STATE.get("queried", 0) + 1
        if isinstance(STATE["answer"], Exception):
            raise STATE["answer"]
        return STATE["answer"]

    mod("app.services.binance", query_order=query_order, BinanceUnavailable=BinanceUnavailable)

    async def fulfill_order(db, order_id):
        STATE["fulfilled"] = STATE.get("fulfilled", 0) + 1
        db.data["orders"][order_id]["status"] = "completed"
        return f"ent_{order_id}"

    mod("app.services.fulfillment", fulfill_order=fulfill_order)


def tearDownModule():
    for k, v in _SAVED.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def make_db(order_over=None, pay_over=None, method="binance_pay"):
    db = FakeDB()
    db.data["orders"] = {"o1": {"user_id": "u1", "status": "awaiting_payment", "final_usdt": 10.0,
                                "expires_at": NOW + timedelta(minutes=30), **(order_over or {})}}
    db.data["payments"] = {"p1": {"order_id": "o1", "payment_method": method, "verification_method": pv.VERIFY_AUTO,
                                  "verification_status": "pending", "binance_prepay_id": "pp1",
                                  "status_history": [], **(pay_over or {})}}
    STATE.clear()
    return db


def verify(db, answer, source="binance_webhook"):
    STATE["answer"] = answer
    return run(pv.verify_binance_order(db, "o1", source=source))


class Orchestration(unittest.TestCase):
    def test_paid_exact_grants_access_once(self):
        db = make_db()
        r = verify(db, bn())
        self.assertEqual((r["outcome"], r["order_status"], r["entitlement_id"]), ("fulfilled", "completed", "ent_o1"))
        p = db.data["payments"]["p1"]
        self.assertEqual((p["verification_status"], p["verified_by"], p["paid_amount_usdt"]), ("verified", "system", 10.0))
        self.assertEqual([e["to"] for e in p["status_history"]], ["verified"])
        self.assertEqual(STATE["audit"], ["binance_payment_verified"])
        # the webhook arrives again (Binance retries): nothing is granted or logged twice
        r2 = verify(db, bn())
        self.assertEqual(r2["outcome"], "noop")
        self.assertEqual(STATE["fulfilled"], 1)
        self.assertEqual(len(db.data["payments"]["p1"]["status_history"]), 1)

    def test_crash_after_mark_is_healed_without_duplicate_history(self):
        db = make_db(pay_over={"verification_status": "verified"})     # marked, order not completed
        r = verify(db, bn())
        self.assertEqual(r["outcome"], "fulfilled")
        self.assertEqual(STATE["fulfilled"], 1)
        self.assertEqual(db.data["payments"]["p1"]["status_history"], [])

    def test_underpaid_goes_to_review_and_grants_nothing(self):
        db = make_db()
        r = verify(db, bn(orderAmount="9"))
        self.assertEqual((r["outcome"], r["order_status"]), ("review", "under_review"))
        self.assertNotIn("fulfilled", STATE)
        self.assertEqual(db.data["orders"]["o1"]["status"], "under_review")
        self.assertEqual(db.data["payments"]["p1"]["review_reason"], "paid_amount_or_currency_mismatch")
        self.assertEqual(db.data["payments"]["p1"]["verification_status"], "pending")
        # repeat → no second history entry
        verify(db, bn(orderAmount="9"))
        self.assertEqual(len(db.data["payments"]["p1"]["status_history"]), 1)

    def test_manual_mode_paid_waits_for_admin(self):
        db = make_db(pay_over={"verification_method": pv.VERIFY_MANUAL})
        self.assertEqual(verify(db, bn())["outcome"], "review")
        self.assertNotIn("fulfilled", STATE)

    def test_pending_changes_nothing_but_the_check_time(self):
        db = make_db()
        r = verify(db, bn(status="PENDING"))
        self.assertEqual(r["outcome"], "wait")
        self.assertEqual(db.data["orders"]["o1"]["status"], "awaiting_payment")
        self.assertEqual(db.data["payments"]["p1"]["attempts"], 1)
        self.assertNotIn("fulfilled", STATE)

    def test_binance_expired_closes_order(self):
        db = make_db()
        r = verify(db, bn(status="EXPIRED"))
        self.assertEqual((r["outcome"], r["order_status"]), ("failed", "expired"))
        self.assertEqual(db.data["payments"]["p1"]["verification_status"], "failed")

    def test_binance_unreachable_leaves_everything_untouched(self):
        db = make_db()
        with self.assertRaises(BinanceUnavailable):
            verify(db, BinanceUnavailable("down"))
        self.assertEqual(db.data["orders"]["o1"]["status"], "awaiting_payment")
        self.assertEqual(db.data["payments"]["p1"]["verification_status"], "pending")
        self.assertNotIn("fulfilled", STATE)

    def test_paid_after_admin_rejection_goes_back_to_admin(self):
        db = make_db(order_over={"status": "failed"}, pay_over={"verification_status": "failed"})
        r = verify(db, bn())
        self.assertEqual(r["outcome"], "review")
        self.assertEqual(db.data["payments"]["p1"]["verification_status"], "pending")
        self.assertNotIn("fulfilled", STATE)

    def test_manual_methods_never_call_binance(self):
        db = make_db(method="usdt_trc20")
        r = verify(db, bn())
        self.assertEqual(r["outcome"], "not_gateway")
        self.assertNotIn("queried", STATE)
        self.assertNotIn("fulfilled", STATE)

    def test_unknown_order(self):
        db = make_db()
        r = run(pv.verify_binance_order(db, "nope", source="x"))
        self.assertEqual(r["outcome"], "not_found")


class TxHashClaims(unittest.TestCase):
    def test_one_hash_one_order(self):
        db = make_db()
        h = "0x" + "ab" * 32
        self.assertTrue(run(pv.claim_txhash(db, h, payment_id="p1", order_id="o1", user_id="u1")))
        self.assertTrue(run(pv.claim_txhash(db, h, payment_id="p1", order_id="o1", user_id="u1")))   # same submit repeated
        self.assertFalse(run(pv.claim_txhash(db, h, payment_id="p2", order_id="o2", user_id="u1")))  # another order
        self.assertFalse(run(pv.claim_txhash(db, h, payment_id="p1", order_id="o1", user_id="u2")))  # another user


# ─── Source-level security contract ───────────────────────────────────────────
class SourceContract(unittest.TestCase):
    misc = SRC("api", "v1", "endpoints", "misc.py")
    orders = SRC("api", "v1", "endpoints", "orders.py")
    admin = SRC("api", "v1", "endpoints", "admin.py")
    ver = SRC("services", "payment_verification.py")

    def webhook(self):
        a = self.misc.index("async def binance_pay_webhook")
        return self.misc[a:]

    def test_webhook_is_only_a_trigger(self):
        w = self.webhook()
        self.assertIn("verify_binance_order", w)
        self.assertNotIn("fulfill_order(", w)                    # cannot grant access itself
        self.assertNotIn("transactAmount", w)                    # never trusts the body's amounts
        self.assertIn("not settings.BINANCE_PAY_API_SECRET", w)  # fail closed
        self.assertIn("status_code=503", w)                      # unreachable Binance → Binance retries

    def test_access_only_through_fulfill_order(self):
        self.assertEqual(self.ver.count("fulfill_order(db, order_id)"), 1)
        self.assertNotIn("create_entitlement", self.ver)
        self.assertNotIn("create_entitlement", self.orders)

    def test_submit_never_grants_access_and_claims_hash(self):
        a = self.orders.index("async def submit_payment")
        b = self.orders.index("# ─── Verify (Binance Pay)")
        body = self.orders[a:b]
        self.assertNotIn("fulfill_order", body)
        self.assertNotIn('"completed"', body.split("# Update order status")[1])
        self.assertIn("claim_txhash", body)

    def test_verify_endpoint_is_owner_only_throttled_and_server_side(self):
        a = self.orders.index("async def verify_order_payment")
        b = self.orders.index("async def retry_order")
        body = self.orders[a:b]
        self.assertIn('od.get("user_id") != user_id', body)
        self.assertIn("verify_wait_seconds", body)
        self.assertIn("verify_binance_order", body)
        self.assertNotIn("body.", body)                          # no client-supplied input at all

    def test_retry_creates_a_new_backend_priced_order(self):
        a = self.orders.index("async def retry_order")
        body = self.orders[a:]
        self.assertIn("_create_order_locked", body)
        self.assertIn("retry_limit_reached", body)
        self.assertNotIn("final_usdt=", body)

    def test_history_written_at_each_transition(self):
        self.assertIn('"order_created"', self.orders)
        self.assertIn('"user_submit"', self.orders)
        self.assertIn('"admin_approve"', self.admin)
        self.assertIn('"admin_reject"', self.admin)
        self.assertIn('"expiry_sweep"', SRC("api", "v1", "endpoints", "admin_payment_methods.py"))

    def test_admin_routes_are_admin_only(self):
        for name in ("payment_detail", "reverify_payment"):
            a = self.admin.index(f"async def {name}")
            self.assertIn("get_current_admin", self.admin[a:a + 200])

    def test_no_secret_in_responses_or_history(self):
        self.assertNotIn("BINANCE_PAY_API_SECRET", self.ver)
        self.assertNotIn("BINANCE_PAY_API_SECRET", self.admin)

    def test_prepay_window_matches_order_window(self):
        self.assertIn("expire_at=expires_at", self.orders)


if __name__ == "__main__":
    unittest.main()
