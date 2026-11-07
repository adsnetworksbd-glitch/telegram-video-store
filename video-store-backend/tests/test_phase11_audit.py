"""
Phase 11 — regression tests for the bugs fixed during the testing / security audit.

OFFLINE: no Firebase, Binance, Telegram or network. Where a function can be executed
for real it is (the real source is loaded, only third-party packages are stubbed);
the rest are source-level contract checks. Nothing here proves live behaviour.
"""
import ast
import asyncio
import hashlib
import hmac
import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "video-store-frontend"
sys.path.insert(0, str(BACKEND))

from tests.test_phase10_part2a_verification import _load_real_binance  # noqa: E402

SRC = lambda *p: (BACKEND / "app" / Path(*p)).read_text()  # noqa: E731
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── tiny in-memory Firestore query fake (equality / `in` filters only) ───────
class FF:
    def __init__(self, field, op, value):
        self.field, self.op, self.value = field, op, value


class _Doc:
    def __init__(self, id_, data):
        self.id, self._d = id_, data

    def to_dict(self):
        return dict(self._d)


class _Query:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter):  # noqa: A002 - mirrors the Firestore API
        def ok(d):
            v = d.get(filter.field)
            return v in filter.value if filter.op == "in" else v == filter.value
        return _Query([(i, d) for i, d in self._docs if ok(d)])

    def limit(self, n):
        return _Query(self._docs[:n])

    async def stream(self):
        for i, d in self._docs:
            yield _Doc(i, d)


class FakeDb:
    def __init__(self, **cols):
        self._cols = {k: list(v.items()) for k, v in cols.items()}

    def collection(self, name):
        return _Query(self._cols.get(name, []))


COL = types.SimpleNamespace(ORDERS="orders", COUPONS="coupons", COUPON_USAGE="coupon_usage")


# ─── 1. Binance webhook signature: hostile input must be a clean "False" ──────
class WebhookHmac(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = _load_real_binance()      # real binance.py, stubbed settings (secret "s3cret")

    def _sig(self, ts, nonce, body):
        return hmac.new(b"s3cret", f"{ts}\n{nonce}\n{body}\n".encode(), hashlib.sha512).hexdigest().upper()

    def test_genuine_hmac_accepted(self):
        self.assertTrue(self.b.verify_binance_webhook("{}", "1", "n", self._sig("1", "n", "{}")))

    def test_wrong_signature_rejected(self):
        self.assertFalse(self.b.verify_binance_webhook("{}", "1", "n", "A" * 128))

    def test_non_ascii_signature_does_not_raise(self):
        # str compare_digest raised TypeError here → HTTP 500 instead of a clean 403
        self.assertFalse(self.b.verify_binance_webhook("{}", "1", "n", "প্রতারণা-ঠিক নয়"))

    def test_lower_case_hex_still_accepted(self):
        self.assertTrue(self.b.verify_binance_webhook("{}", "1", "n", self._sig("1", "n", "{}").lower()))


# ─── 2. Coupon: one single-use coupon must not back several open orders ───────
def _load_coupon_module():
    saved = {k: sys.modules.get(k) for k in (
        "google", "google.cloud", "google.cloud.firestore_v1", "google.cloud.firestore_v1.base_query",
        "app.db", "app.db.firebase", "app.schemas")}
    try:
        for name in ("google", "google.cloud"):
            sys.modules[name] = types.ModuleType(name)
        fs = types.ModuleType("google.cloud.firestore_v1")
        fs.AsyncClient = object
        bq = types.ModuleType("google.cloud.firestore_v1.base_query")
        bq.FieldFilter = FF
        sys.modules["google.cloud.firestore_v1"] = fs
        sys.modules["google.cloud.firestore_v1.base_query"] = bq
        fb = types.ModuleType("app.db.firebase")
        fb.Col = types.SimpleNamespace(COUPONS="coupons", COUPON_USAGE="coupon_usage")
        sys.modules.setdefault("app.db", types.ModuleType("app.db"))
        sys.modules["app.db.firebase"] = fb
        sc = types.ModuleType("app.schemas")

        class CouponValidation:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        sc.CouponValidation = CouponValidation
        sys.modules["app.schemas"] = sc
        spec = importlib.util.spec_from_file_location("coupon_real", BACKEND / "app" / "services" / "coupon.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class CouponPendingUses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coupon = _load_coupon_module()

    def _db(self, per_user_limit=1, used_by_user=0):
        usage = {f"u{i}": {"coupon_id": "c1", "user_id": "u1"} for i in range(used_by_user)}
        return FakeDb(
            coupons={"c1": {"code": "SAVE", "is_active": True, "discount_type": "fixed_bdt",
                            "discount_value": 50, "per_user_limit": per_user_limit}},
            coupon_usage=usage,
        )

    def _validate(self, db, **kw):
        return run(self.coupon.validate_coupon(db, "save", "u1", "video", "v1", 500.0, **kw))

    def test_fresh_coupon_is_valid(self):
        self.assertTrue(self._validate(self._db()).valid)

    def test_single_use_coupon_already_held_by_another_open_order_is_refused(self):
        self.assertFalse(self._validate(self._db(), pending_uses=1).valid)

    def test_multi_use_coupon_allows_another_open_order_until_the_limit(self):
        db = self._db(per_user_limit=2)
        self.assertTrue(self._validate(db, pending_uses=1).valid)
        self.assertFalse(self._validate(db, pending_uses=2).valid)

    def test_recorded_usage_still_counts(self):
        self.assertFalse(self._validate(self._db(used_by_user=1)).valid)

    def test_default_keeps_old_behaviour(self):
        self.assertTrue(self.coupon.validate_coupon.__defaults__ == (0,))


def _extract_function(path: Path, name: str):
    """Compile ONE function out of a module without importing the module (real code, no stubs of it)."""
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    ns = {"Col": COL, "FieldFilter": FF, "datetime": datetime}
    exec(compile(ast.Module([fn], []), str(path), "exec"), ns)
    return ns[name]


class OrdersCouponPendingUses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fn = staticmethod(_extract_function(
            BACKEND / "app" / "api" / "v1" / "endpoints" / "orders.py", "_coupon_pending_uses"))

    def _orders(self):
        soon, past = NOW + timedelta(minutes=20), NOW - timedelta(minutes=1)
        return {
            "same_content": {"user_id": "u1", "status": "awaiting_payment", "coupon_code": "SAVE",
                             "content_type": "video", "content_id": "v1", "expires_at": soon},
            "other_open": {"user_id": "u1", "status": "awaiting_payment", "coupon_code": "SAVE",
                           "content_type": "video", "content_id": "v2", "expires_at": soon},
            "other_expired": {"user_id": "u1", "status": "awaiting_payment", "coupon_code": "SAVE",
                              "content_type": "video", "content_id": "v3", "expires_at": past},
            "other_in_review": {"user_id": "u1", "status": "under_review", "coupon_code": "save",
                                "content_type": "package", "content_id": "p1", "expires_at": past},
            "other_coupon": {"user_id": "u1", "status": "awaiting_payment", "coupon_code": "OTHER",
                             "content_type": "video", "content_id": "v4", "expires_at": soon},
            "other_user": {"user_id": "u2", "status": "awaiting_payment", "coupon_code": "SAVE",
                           "content_type": "video", "content_id": "v5", "expires_at": soon},
            "completed": {"user_id": "u1", "status": "completed", "coupon_code": "SAVE",
                          "content_type": "video", "content_id": "v6", "expires_at": past},
        }

    def test_counts_only_this_users_live_orders_for_other_content_with_this_coupon(self):
        db = FakeDb(orders=self._orders())
        # other_open + other_in_review; NOT same content, expired, other coupon/user, completed
        self.assertEqual(run(self.fn(db, "u1", " save ", "video", "v1", NOW)), 2)

    def test_zero_when_nothing_else_is_open(self):
        self.assertEqual(run(self.fn(FakeDb(orders={}), "u1", "SAVE", "video", "v1", NOW)), 0)


# ─── 3. Source-level contracts for the remaining fixes ────────────────────────
class SourceContracts(unittest.TestCase):
    def test_validation_handler_never_returns_raw_pydantic_errors(self):
        s = SRC("main.py")
        body = s[s.index("async def validation_exception_handler"):s.index("@app.exception_handler(Exception)")]
        self.assertNotIn('"errors": exc.errors()', body)     # ctx holds a ValueError object → 500
        self.assertNotIn('"input"', body)

    def test_webhook_rejects_non_utf8_and_non_object_bodies(self):
        s = SRC("api", "v1", "endpoints", "misc.py")
        self.assertIn('body_bytes.decode("utf-8")', s)
        self.assertIn("UnicodeDecodeError", s)
        self.assertIn("if not isinstance(payload, dict)", s)
        self.assertIn("if not isinstance(biz_data, dict)", s)

    def test_webhook_signature_compare_is_bytes(self):
        s = SRC("services", "binance.py")
        self.assertIn('signature.upper().encode("utf-8")', s)

    def test_order_creation_holds_a_coupon_lock_and_counts_pending_uses(self):
        s = SRC("api", "v1", "endpoints", "orders.py")
        self.assertIn("pending_uses=await _coupon_pending_uses(", s)
        self.assertIn('_order_lock(uid, "coupon"', s)
        self.assertIn("async def _create_order_unlocked", s)
        # retry still goes through the same (locked) creation path
        self.assertIn("_create_order_locked(db, req, user_id)", s)

    def test_ids_used_as_document_ids_are_pattern_locked(self):
        s = SRC("schemas", "__init__.py")
        self.assertIn('pattern=r"^[A-Za-z0-9_-]+$")\n    server_token', s)
        self.assertIn("invalid id", s)

    def test_bot_has_no_placeholder_url_and_forwards_only_wellformed_codes(self):
        s = SRC("bot", "main.py")
        self.assertNotIn("your-frontend", s)
        self.assertIn("settings.mini_app_url", s)
        self.assertIn('re.fullmatch(r"VS-[A-Z0-9]{7}"', s)

    def test_login_start_param_is_only_a_referral_hint(self):
        s = SRC("api", "v1", "endpoints", "auth.py")
        # user id still comes from verified Telegram data only
        self.assertIn('user_id = str(tg_user["id"])', s)
        self.assertIn("body.start_param", s)

    def test_frontend_headers_allow_telegram_web_but_not_arbitrary_framing(self):
        v = json.loads((FRONTEND / "vercel.json").read_text())
        hdrs = {h["key"]: h["value"] for h in v["headers"][0]["headers"]}
        self.assertNotIn("X-Frame-Options", hdrs)             # DENY blocks Telegram Web's iframe
        csp = hdrs["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'self' https://web.telegram.org", csp)
        self.assertNotIn("*", csp)

    def test_frontend_only_opens_https_checkout_links(self):
        for f in ("pages/Payment/index.tsx", "pages/PaymentPending/index.tsx"):
            self.assertIn("/^https:\\/\\//i.test(", (FRONTEND / "src" / f).read_text(), f)

    def test_firestore_rules_deny_all_client_access(self):
        rules = (BACKEND / "firestore.rules").read_text()
        self.assertIn("allow read, write: if false;", rules)
        self.assertNotRegex(rules, r"allow\s+\w+(\s*,\s*\w+)*\s*:\s*if\s+(true|request\.auth)")

    def test_no_secret_values_are_committed(self):
        import re
        token = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")        # Telegram bot-token shape
        private = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
        for f in BACKEND.parent.rglob("*"):
            if not f.is_file() or "node_modules" in f.parts or f.suffix in (".png", ".jpg", ".zip"):
                continue
            self.assertNotIn(f.name, ("private.pem", "public.pem", "firebase-service-account.json", ".env"), str(f))
            if "tests" in f.parts:
                continue                                              # fixtures may hold fake keys
            text = f.read_text(errors="ignore")
            self.assertIsNone(private.search(text), f"private key material in {f}")
            for m in token.finditer(text):
                self.assertIn("xxxx", m.group(0).lower(), f"real-looking bot token in {f}")   # placeholders only

if __name__ == "__main__":
    unittest.main()
