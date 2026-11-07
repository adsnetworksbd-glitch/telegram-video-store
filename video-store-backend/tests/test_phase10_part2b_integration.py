"""
Phase 10 Part 2B — purchase / access integration: crash-safe idempotent fulfilment,
single ledger entry, manual-review rules, user-safe order view.

OFFLINE. The REAL fulfillment.py / transaction.py / order_view.py run against an
in-memory fake Firestore (transactions modelled as serialised). NOT tested here:
real Firestore transaction retries, real Binance, pydantic schema import (pydantic
is not installed in the sandbox) — see docs/PHASE10_PART2B_NOTES.md.
"""
import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services import order_view as ov  # noqa: E402  (pure, no third-party imports)

SRC = lambda *p: (BACKEND / "app" / Path(*p)).read_text()  # noqa: E731
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── fake Firestore ───────────────────────────────────────────────────────────
class AlreadyExists(Exception):
    pass


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
    def _s(self):
        return self.db.data.setdefault(self.col, {})

    async def get(self, **_kw):
        await asyncio.sleep(0)          # let concurrent callers interleave
        return _Snap(self, self._s.get(self.id))

    async def create(self, data):
        await asyncio.sleep(0)
        if self.id in self._s:
            raise AlreadyExists()
        self._s[self.id] = dict(data)

    async def set(self, data):
        self._s[self.id] = dict(data)

    async def update(self, data):
        self._s[self.id].update(data)


class _Coll:
    def __init__(self, db, col):
        self.db, self.col = db, col

    def document(self, id_):
        return _Ref(self.db, self.col, id_)


class _Txn:
    def update(self, ref, data):
        ref._s[ref.id].update(data)


class FakeDB:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return _Coll(self, name)

    def transaction(self):
        return _Txn()


STUBS = ["google", "google.cloud", "google.cloud.firestore_v1", "google.cloud.firestore_v1.async_transaction",
         "google.api_core", "google.api_core.exceptions", "app.db", "app.db.firebase",
         "app.services.entitlement", "app.services.coupon", "app.services.referral", "app.utils", "app.utils.audit"]
_SAVED: dict = {}
CALLS: dict = {}
F = T = None


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, BACKEND / "app" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def setUpModule():
    global F, T
    for k in STUBS:
        _SAVED[k] = sys.modules.get(k)

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    lock = asyncio.Lock  # one lock per event loop is created lazily below

    def async_transactional(fn):
        state = {}

        async def wrapper(txn):
            loop = asyncio.get_running_loop()
            lk = state.setdefault(loop, lock())
            async with lk:               # serialisable, like a Firestore transaction
                return await fn(txn)
        return wrapper

    mod("google"); mod("google.cloud")
    mod("google.cloud.firestore_v1", AsyncClient=object)
    mod("google.cloud.firestore_v1.async_transaction", async_transactional=async_transactional)
    mod("google.api_core"); mod("google.api_core.exceptions", AlreadyExists=AlreadyExists)
    mod("app.db"); mod("app.db.firebase", Col=types.SimpleNamespace(
        ORDERS="orders", PAYMENTS="payments", VIDEOS="videos", PACKAGES="packages",
        USERS="users", TRANSACTIONS="transactions", ENTITLEMENTS="entitlements"))
    mod("app.utils")

    async def audit_log(**kw):
        CALLS.setdefault("audit", []).append(kw["action"])

    mod("app.utils.audit", audit_log=audit_log)

    async def create_entitlement(db, user_id, content_type, content_id, access_source, duration_hours,
                                 order_id=None, included_video_ids=None, entitlement_id=None, **_):
        CALLS.setdefault("ent", []).append({"duration_hours": duration_hours, "included": included_video_ids,
                                            "source": access_source})
        await db.collection("entitlements").document(entitlement_id).create(
            {"user_id": user_id, "content_id": content_id, "order_id": order_id, "duration_hours": duration_hours})
        return entitlement_id

    mod("app.services.entitlement", create_entitlement=create_entitlement)

    async def record_coupon_usage(*a, **k):
        CALLS["coupon"] = CALLS.get("coupon", 0) + 1

    mod("app.services.coupon", record_coupon_usage=record_coupon_usage)

    async def process_referral_on_purchase(db, uid, oid):
        CALLS["referral"] = CALLS.get("referral", 0) + 1

    mod("app.services.referral", process_referral_on_purchase=process_referral_on_purchase)

    T = _load("transaction_real", "services/transaction.py")
    mod("app.services.transaction", record_transaction=T.record_transaction)
    F = _load("fulfillment_real", "services/fulfillment.py")


def tearDownModule():
    for k, v in _SAVED.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def make_db(status="under_review", content="video", **order_over):
    CALLS.clear()
    db = FakeDB()
    db.data["orders"] = {"o1": {"user_id": "u1", "content_type": content, "content_id": "c1", "final_bdt": 230.0,
                                "status": status, "entitlement_id": None, **order_over}}
    db.data["users"] = {"u1": {"total_spent_bdt": 100.0}}
    db.data["videos"] = {"c1": {"purchase_duration_hours": 24, "purchase_count": 3}}
    db.data["packages"] = {"c1": {"duration_type": "lifetime", "video_ids": ["v1", "v2"], "purchase_count": 0}}
    return db


class Fulfilment(unittest.TestCase):
    def test_happy_path_one_of_everything(self):
        db = make_db()
        ent = run(F.fulfill_order(db, "o1"))
        self.assertEqual(ent, "ent_o1")
        self.assertEqual(db.data["orders"]["o1"]["status"], "completed")
        self.assertEqual(db.data["orders"]["o1"]["entitlement_id"], "ent_o1")
        self.assertEqual(list(db.data["entitlements"]), ["ent_o1"])
        self.assertEqual(list(db.data["transactions"]), ["txn_purchase_o1"])
        self.assertEqual(db.data["users"]["u1"]["total_spent_bdt"], 330.0)
        self.assertEqual(db.data["videos"]["c1"]["purchase_count"], 4)
        self.assertEqual((CALLS["referral"], CALLS["audit"]), (1, ["order_fulfilled"]))

    def test_repeat_calls_change_nothing(self):
        db = make_db()
        run(F.fulfill_order(db, "o1"))
        self.assertEqual(run(F.fulfill_order(db, "o1")), "ent_o1")
        self.assertEqual(run(F.fulfill_order(db, "o1")), "ent_o1")
        self.assertEqual(len(db.data["entitlements"]), 1)
        self.assertEqual(len(db.data["transactions"]), 1)
        self.assertEqual(db.data["users"]["u1"]["total_spent_bdt"], 330.0)
        self.assertEqual(db.data["videos"]["c1"]["purchase_count"], 4)
        self.assertEqual(CALLS["referral"], 1)

    def test_concurrent_webhook_user_check_and_admin_create_one_purchase(self):
        db = make_db()

        async def go():
            return await asyncio.gather(*[F.fulfill_order(db, "o1") for _ in range(6)])

        res = run(go())
        self.assertEqual(set(res), {"ent_o1"})
        self.assertEqual(len(db.data["entitlements"]), 1)
        self.assertEqual(len(db.data["transactions"]), 1)
        self.assertEqual(db.data["users"]["u1"]["total_spent_bdt"], 330.0)      # not 100 + 6×230
        self.assertEqual(db.data["videos"]["c1"]["purchase_count"], 4)
        self.assertEqual(CALLS["referral"], 1)
        self.assertEqual(CALLS["audit"], ["order_fulfilled"])

    def test_crash_after_entitlement_is_recovered(self):
        db = make_db()
        db.data["entitlements"] = {"ent_o1": {"user_id": "u1"}}       # step 1 done, process died
        self.assertEqual(run(F.fulfill_order(db, "o1")), "ent_o1")
        self.assertEqual(db.data["orders"]["o1"]["status"], "completed")
        self.assertEqual(len(db.data["transactions"]), 1)             # ledger row now exists
        self.assertEqual(len(db.data["entitlements"]), 1)             # access not duplicated

    def test_crash_after_ledger_does_not_double_charge_total(self):
        db = make_db()
        db.data["entitlements"] = {"ent_o1": {"user_id": "u1"}}
        run(T.record_transaction(db, "u1", "purchase", 230.0, "debit", "order", "o1", "x",
                                 tx_id=F.ledger_tx_id("o1")))        # step 2 done, process died
        self.assertEqual(db.data["users"]["u1"]["total_spent_bdt"], 330.0)
        run(F.fulfill_order(db, "o1"))
        self.assertEqual(db.data["orders"]["o1"]["status"], "completed")
        self.assertEqual(len(db.data["transactions"]), 1)
        self.assertEqual(db.data["users"]["u1"]["total_spent_bdt"], 330.0)

    def test_rejected_or_refunded_or_missing_never_get_access(self):
        for st in ("failed", "refunded"):
            db = make_db(status=st)
            self.assertIsNone(run(F.fulfill_order(db, "o1")), st)
            self.assertNotIn("entitlements", db.data)
            self.assertNotIn("transactions", db.data)
            self.assertEqual(db.data["orders"]["o1"]["status"], st)
        self.assertIsNone(run(F.fulfill_order(make_db(), "nope")))

    def test_rejection_racing_an_approval_grants_nothing_afterwards(self):
        db = make_db()
        db.data["orders"]["o1"]["status"] = "failed"                 # admin rejected first
        self.assertIsNone(run(F.fulfill_order(db, "o1")))
        self.assertNotIn("entitlements", db.data)

    def test_duration_rules_lifetime_and_custom(self):
        db = make_db()
        run(F.fulfill_order(db, "o1"))
        self.assertEqual(CALLS["ent"][0]["duration_hours"], 24)      # video: custom hours
        self.assertEqual(CALLS["ent"][0]["source"], "individual_purchase")

        db = make_db(content="package")
        run(F.fulfill_order(db, "o1"))
        self.assertEqual(CALLS["ent"][0]["duration_hours"], 0)       # package lifetime
        self.assertEqual(CALLS["ent"][0]["included"], ["v1", "v2"])
        self.assertEqual(CALLS["ent"][0]["source"], "package_purchase")

        db = make_db(content="package")
        db.data["packages"]["c1"].update({"duration_type": "custom", "duration_hours": 72})
        run(F.fulfill_order(db, "o1"))
        self.assertEqual(CALLS["ent"][0]["duration_hours"], 72)      # package custom

    def test_side_effect_failure_does_not_undo_access(self):
        db = make_db(coupon_code="SAVE", discount_bdt=20.0)
        orig = sys.modules["app.services.coupon"].record_coupon_usage

        async def boom(*a, **k):
            raise RuntimeError("coupon store down")

        F.record_coupon_usage = boom
        try:
            self.assertEqual(run(F.fulfill_order(db, "o1")), "ent_o1")
        finally:
            F.record_coupon_usage = orig
        self.assertEqual(db.data["orders"]["o1"]["status"], "completed")


class Ledger(unittest.TestCase):
    def test_random_id_still_works_for_other_callers(self):
        db = make_db()
        a = run(T.record_transaction(db, "u1", "refund", 10, "credit", "order", "o1", "r"))
        b = run(T.record_transaction(db, "u1", "refund", 10, "credit", "order", "o1", "r"))
        self.assertNotEqual(a, b)

    def test_deterministic_id_recorded_once(self):
        db = make_db()
        for _ in range(3):
            run(T.record_transaction(db, "u1", "purchase", 50.0, "debit", "order", "o9", "p", tx_id="txn_x"))
        self.assertEqual(len(db.data["transactions"]), 1)
        self.assertEqual(db.data["users"]["u1"]["total_spent_bdt"], 150.0)


# ─── user-safe projection ─────────────────────────────────────────────────────
class OrderView(unittest.TestCase):
    def test_review_codes(self):
        rc = ov.review_code
        self.assertIsNone(rc("awaiting_payment", {}))
        self.assertIsNone(rc("completed", {"review_reason": "x"}))
        self.assertEqual(rc("under_review", {}), "user_submitted")
        self.assertEqual(rc("under_review", {"review_reason": "paid_amount_or_currency_mismatch"}), "amount_mismatch")
        self.assertEqual(rc("under_review", {"review_reason": "paid_reference_mismatch"}), "reference_mismatch")
        self.assertEqual(rc("under_review", {"review_reason": "binance_paid_manual_mode"}), "manual_mode")
        self.assertEqual(rc("under_review", {"review_reason": "paid_but_order_failed"}), "late_payment")
        self.assertEqual(rc("under_review", {"review_reason": "something_new"}), "other")

    def test_timeline_hides_notes_and_actor_names(self):
        h = [
            {"at": NOW + timedelta(minutes=5), "from": "under_review", "to": "rejected", "by": "admin_rahim",
             "source": "admin_reject", "note": "fake screenshot, ban him"},
            {"at": NOW, "from": None, "to": "awaiting_payment", "by": "u1", "source": "order_created", "note": "binance_pay · 2 USDT"},
            {"at": "garbage"},
        ]
        t = ov.timeline(h)
        self.assertEqual([e["step"] for e in t], ["created", "rejected"])
        self.assertEqual(set(t[0]), {"at", "step", "source"})
        self.assertNotIn("admin_rahim", str(t))
        self.assertNotIn("fake screenshot", str(t))

    def test_retry_info(self):
        self.assertEqual(ov.retry_info("awaiting_payment", 0, 5, False), {"allowed": False, "remaining": None})
        self.assertEqual(ov.retry_info("failed", 2, 5, False), {"allowed": True, "remaining": 3})
        self.assertEqual(ov.retry_info("expired", 5, 5, False), {"allowed": False, "remaining": 0})
        self.assertEqual(ov.retry_info("expired", 99, 0, False), {"allowed": True, "remaining": None})  # no cap
        self.assertEqual(ov.retry_info("failed", 0, 5, True), {"allowed": False, "remaining": None})    # has access


# ─── Source-level contract ────────────────────────────────────────────────────
class SourceContract(unittest.TestCase):
    orders = SRC("api", "v1", "endpoints", "orders.py")
    admin = SRC("api", "v1", "endpoints", "admin.py")
    ful = SRC("services", "fulfillment.py")

    def test_fulfilment_resumes_instead_of_returning_on_existing_entitlement(self):
        a = self.ful.index("except AlreadyExists")
        self.assertNotIn("return", self.ful[a:a + 200].split("# 2.")[0])

    def test_only_failed_closed_states_block_fulfilment(self):
        self.assertIn("FULFILLABLE_STATUSES", self.ful)
        self.assertNotIn('"failed"', self.ful.split("FULFILLABLE_STATUSES = frozenset({")[1].split("})")[0])
        self.assertNotIn('"refunded"', self.ful.split("FULFILLABLE_STATUSES = frozenset({")[1].split("})")[0])

    def test_user_order_view_never_exposes_admin_data(self):
        a = self.orders.index("async def get_order")
        b = self.orders.index("@router.post(\"/orders/{order_id}/submit\"")
        body = self.orders[a:b]
        for secret in ("admin_note", "verified_by", "status_history\"]", "user_note", "screenshot_url"):
            self.assertNotIn(secret, body)
        self.assertIn("public_timeline", body)
        self.assertIn("review_code(", body)

    def test_submit_is_serialised_per_order(self):
        a = self.orders.index("async def submit_payment")
        self.assertIn("_order_lock(user_id, \"submit\", order_id)", self.orders[a:a + 900])

    def test_admin_approve_requires_real_fulfilment(self):
        a = self.admin.index("async def approve_payment")
        b = self.admin.index("async def reject_payment")
        body = self.admin[a:b]
        self.assertIn("ent_id is None", body)
        self.assertIn('!= "under_review"', body)           # only reviewed orders can be approved

    def test_every_grant_path_goes_through_fulfill_order(self):
        for name in ("orders.py", "misc.py", "admin.py"):
            src = SRC("api", "v1", "endpoints", name)
            self.assertNotIn("create_entitlement(", src, name)


if __name__ == "__main__":
    unittest.main()
