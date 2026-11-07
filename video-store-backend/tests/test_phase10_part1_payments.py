"""
Phase 10 Part 1 — payment method registry + order-creation contract.
Offline: pure functions + source-level checks (no Firestore / FastAPI needed).
"""
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import payment_methods as pm  # noqa: E402

ORDERS = (BACKEND / "app" / "api" / "v1" / "endpoints" / "orders.py").read_text()
TRC = "T" + "A" * 33
EVM = "0x" + "a1" * 20


def doc(**kw):
    base = {"name": "X", "type": "usdt_trc20", "is_enabled": True, "wallet_address": TRC}
    base.update(kw)
    return base


class Normalize(unittest.TestCase):
    def test_legacy_doc_gets_defaults(self):
        m = pm.normalize_method("m1", {"name": "USDT TRC20", "type": "usdt_trc20", "is_enabled": True,
                                       "wallet_address": TRC, "network_name": "TRON"})
        self.assertEqual(m["kind"], "wallet")
        self.assertEqual(m["network_name"], "TRON")          # admin value wins
        self.assertEqual(m["currency"], "USDT")
        self.assertTrue(m["manual_review_supported"])
        self.assertFalse(m["auto_verification_supported"])
        self.assertEqual(m["min_amount_usdt"], 0.5)
        self.assertIsNone(m["max_amount_usdt"])

    def test_default_network_label(self):
        m = pm.normalize_method("m", doc(type="usdt_erc20", wallet_address=EVM, network_name=None))
        self.assertEqual(m["network_name"], "Ethereum (ERC20)")

    def test_binance_pay_is_gateway_without_address(self):
        m = pm.normalize_method("bp", {"type": "binance_pay", "is_enabled": True, "wallet_address": TRC})
        self.assertEqual(m["kind"], "gateway")
        self.assertIsNone(m["wallet_address"])
        self.assertTrue(m["auto_verification_supported"])

    def test_binance_id_mirrors_pay_id_into_wallet_address(self):
        m = pm.normalize_method("bi", {"type": "binance_id", "is_enabled": True, "pay_id": "123456789"})
        self.assertEqual((m["pay_id"], m["wallet_address"]), ("123456789", "123456789"))
        m2 = pm.normalize_method("bi", {"type": "binance_id", "is_enabled": True, "wallet_address": "987654321"})
        self.assertEqual(m2["pay_id"], "987654321")          # old docs keep working

    def test_custom_type(self):
        m = pm.normalize_method("c", {"type": "bkash_usd", "is_enabled": True, "instructions_text": "Send"})
        self.assertEqual(m["kind"], "custom")
        self.assertTrue(pm.is_payable(m))

    def test_timeout_clamped(self):
        self.assertEqual(pm.timeout_minutes({"payment_timeout_minutes": 0}), pm.MIN_TIMEOUT_MIN)
        self.assertEqual(pm.timeout_minutes({"payment_timeout_minutes": 10**6}), pm.MAX_TIMEOUT_MIN)
        self.assertEqual(pm.timeout_minutes({"payment_timeout_minutes": "x"}), pm.DEFAULT_TIMEOUT_MIN)

    def test_no_secret_fields_in_public_view(self):
        m = pm.normalize_method("bp", {"type": "binance_pay", "api_secret": "S", "secret": "S"})
        self.assertFalse([k for k in m if "secret" in k or "key" in k])


class Payable(unittest.TestCase):
    def test_disabled_never_payable(self):
        self.assertFalse(pm.is_payable(pm.normalize_method("a", doc(is_enabled=False))))

    def test_placeholder_wallet_hidden(self):
        m = pm.normalize_method("a", doc(wallet_address="TYour_TRC20_Wallet_Address_Here"))
        self.assertFalse(pm.is_payable(m))

    def test_valid_wallets(self):
        self.assertTrue(pm.is_payable(pm.normalize_method("a", doc())))
        self.assertTrue(pm.is_payable(pm.normalize_method("b", doc(type="usdt_bep20", wallet_address=EVM))))

    def test_wrong_network_address_hidden(self):
        self.assertFalse(pm.is_payable(pm.normalize_method("a", doc(type="usdt_bep20", wallet_address=TRC))))

    def test_gateway_needs_no_address(self):
        self.assertTrue(pm.is_payable(pm.normalize_method("bp", {"type": "binance_pay", "is_enabled": True})))


class Limits(unittest.TestCase):
    def setUp(self):
        self.m = pm.normalize_method("a", doc(min_amount_usdt=1, max_amount_usdt=50))

    def test_below_min(self):
        self.assertIn("ন্যূনতম", pm.amount_problem(self.m, 0.99))

    def test_above_max(self):
        self.assertIn("সর্বোচ্চ", pm.amount_problem(self.m, 50.01))

    def test_edges_ok(self):
        self.assertIsNone(pm.amount_problem(self.m, 1))
        self.assertIsNone(pm.amount_problem(self.m, 50))


class AdminValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(pm.config_problems(doc()), [])

    def test_bad_wallet(self):
        self.assertTrue(pm.config_problems(doc(wallet_address="nope")))

    def test_enabled_wallet_needs_address(self):
        self.assertTrue(pm.config_problems(doc(wallet_address=None)))

    def test_max_below_min(self):
        self.assertTrue(pm.config_problems(doc(min_amount_usdt=5, max_amount_usdt=2)))

    def test_pay_id_required_and_numeric(self):
        self.assertTrue(pm.config_problems({"name": "B", "type": "binance_id"}))
        self.assertTrue(pm.config_problems({"name": "B", "type": "binance_id", "pay_id": "abc"}))
        self.assertEqual(pm.config_problems({"name": "B", "type": "binance_id", "pay_id": "123456789"}), [])

    def test_custom_type_slug(self):
        self.assertEqual(pm.config_problems({"name": "bKash", "type": "bkash_usd"}), [])
        self.assertTrue(pm.config_problems({"name": "bKash", "type": "Bad Type!"}))

    def test_qr_must_be_https(self):
        self.assertTrue(pm.config_problems(doc(qr_code_url="http://x/qr.png")))

    def test_needs_some_verification_path(self):
        self.assertTrue(pm.config_problems(doc(auto_verification_supported=False, manual_review_supported=False)))

    def test_gateway_auto_is_an_admin_choice(self):
        # Part 2A: admin may switch Binance Pay to manual review (payment is then held for an admin,
        # never auto-granted) — but a method must always keep at least one verification path.
        self.assertEqual(pm.config_problems({"name": "BP", "type": "binance_pay", "auto_verification_supported": False}), [])
        self.assertTrue(pm.config_problems({"name": "BP", "type": "binance_pay",
                                            "auto_verification_supported": False, "manual_review_supported": False}))


class OrderCreationContract(unittest.TestCase):
    """Source-level guarantees for the security rules of the task."""

    def body(self):
        a = ORDERS.index("async def _create_order_locked")
        return ORDERS[a:ORDERS.index('@router.get("/orders/history"')]

    def test_request_has_no_price_user_or_status_fields(self):
        schemas = (BACKEND / "app" / "schemas" / "__init__.py").read_text()
        m = re.search(r"class OrderCreateRequest\(BaseModel\):(.*?)\n\n\n", schemas, re.S).group(1)
        names = set(re.findall(r"(?m)^\s{4}(\w+):", m))
        self.assertEqual(names, {"content_type", "content_id", "payment_method_id", "coupon_code"})

    def test_user_id_comes_from_auth_dependency(self):
        self.assertIn("user_id: str = Depends(get_current_user)", ORDERS[ORDERS.index("async def create_order"):])

    def test_status_is_server_set(self):
        self.assertIn('"status": "awaiting_payment"', self.body())

    def test_amount_from_backend_rate_and_price(self):
        b = self.body()
        self.assertIn('price_bdt', b)
        self.assertIn("usdt_to_bdt_rate", b)
        self.assertNotIn("body.amount", b)

    def test_limits_enforced(self):
        self.assertIn("amount_problem(method, final_usdt)", self.body())

    def test_duplicate_prevention_present(self):
        b = self.body()
        self.assertIn("reused=True", b)
        self.assertIn("payment_submitted", b)
        self.assertIn("_order_lock(", ORDERS)

    def test_payment_snapshot_stored(self):
        for f in ('"wallet_address"', '"pay_id"', '"network"', '"currency"', '"payment_method_id"'):
            self.assertIn(f, self.body())

    def test_binance_secret_not_in_responses(self):
        self.assertNotIn("BINANCE_PAY_API_SECRET", ORDERS)

    def test_submit_rejects_expired(self):
        self.assertIn('od["status"] == "expired"', ORDERS)


class AdminApiContract(unittest.TestCase):
    SRC = (BACKEND / "app" / "api" / "v1" / "endpoints" / "admin_payment_methods.py").read_text()

    def test_all_routes_admin_protected(self):
        routes = len(re.findall(r"@router\.(get|post|put|patch)\(", self.SRC))
        self.assertEqual(routes, self.SRC.count("Depends(get_current_admin)"))
        self.assertGreaterEqual(routes, 5)

    def test_create_never_overwrites(self):
        self.assertIn(".create(data)", self.SRC)

    def test_registered_in_router(self):
        self.assertIn("admin_payment_methods", (BACKEND / "app" / "api" / "v1" / "router.py").read_text())


if __name__ == "__main__":
    unittest.main()
