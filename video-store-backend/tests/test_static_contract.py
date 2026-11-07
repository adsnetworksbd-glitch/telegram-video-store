"""
Static contract + pure-unit tests. Standard library only (plus `cryptography`
for the Fernet round-trip) so they run WITHOUT FastAPI/Firebase installed.

These do NOT replace runtime tests: they never start FastAPI, never touch
Firestore, and never execute the endpoints. See PHASE5_FINAL_REPORT_BN.md.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "video-store-backend" / "app"
FRONTEND = ROOT / "video-store-frontend" / "src"
EP = BACKEND / "api" / "v1" / "endpoints"


def backend_routes():
    """(METHOD, normalized_path, file, lineno) for every @router.<verb>(...)."""
    routes = []
    for f in sorted(EP.glob("*.py")):
        tree = ast.parse(f.read_text())
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                    and getattr(node.value.func, "id", "") == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "prefix":
                        prefix = kw.value.value
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                            and getattr(dec.func.value, "id", "") == "router" \
                            and dec.func.attr in ("get", "post", "put", "patch", "delete"):
                        path = prefix + dec.args[0].value
                        routes.append((dec.func.attr.upper(), re.sub(r"\{[^}]+\}", "{}", path), f.name, dec.lineno))
    return routes


def frontend_calls():
    text = (FRONTEND / "api" / "index.ts").read_text()
    calls = []
    for m in re.finditer(r"api\.(get|post|put|patch|delete)<[\s\S]*?>\(\s*([`'])(.+?)\2", text):
        path = re.sub(r"\$\{[^}]+\}", "{}", m.group(3))
        calls.append((m.group(1).upper(), path))
    return calls


class ApiContract(unittest.TestCase):
    def test_frontend_calls_exist_in_backend(self):
        be = {(m, p) for m, p, _, _ in backend_routes()}
        fe = frontend_calls()
        self.assertGreater(len(fe), 20, "frontend call parser found too few calls")
        missing = [c for c in fe if c not in be]
        self.assertEqual(missing, [], f"frontend calls with no backend route: {missing}")

    def test_static_routes_declared_before_param_routes(self):
        """/orders/history must precede /orders/{order_id} (FastAPI matches in order)."""
        by_file = {}
        for m, p, f, ln in backend_routes():
            by_file.setdefault((f, m), []).append((ln, p))
        for (f, m), items in by_file.items():
            items.sort()
            for i, (ln, p) in enumerate(items):
                if p.endswith("/{}"):
                    base = p[:-3]
                    for ln2, p2 in items[:i]:
                        pass
                    later_static = [p2 for ln2, p2 in items[i + 1:] if p2.startswith(base + "/") and "{}" not in p2[len(base) + 1:]]
                    self.assertEqual(later_static, [], f"{f}: {m} {p} shadows later static routes {later_static}")

    def test_admin_routes_all_require_admin_dependency(self):
        src = (EP / "admin.py").read_text()
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name != "admin_login" and not node.name.startswith("_"):
                self.assertIn("get_current_admin", ast.unparse(node.args), f"{node.name} lacks admin auth")


class SecurityStatic(unittest.TestCase):
    def test_webhooks_fail_closed(self):
        ads = (EP / "ads.py").read_text()
        self.assertNotIn("if settings.MONETAG_CALLBACK_SECRET:", ads)
        # Phase 9: signature check lives in the provider module; the endpoint
        # passes the configured secret (empty secret → provider rejects).
        self.assertIn("getattr(settings, provider.secret_setting", ads)
        self.assertIn("verify_hmac_sha256_hex(secret, body, sig)",
                      (BACKEND / "services" / "ad_providers" / "monetag.py").read_text())
        self.assertEqual(
            __import__("importlib").import_module("app.services.ad_providers").get_provider("monetag").secret_setting,
            "MONETAG_CALLBACK_SECRET")
        misc = (EP / "misc.py").read_text()
        self.assertNotIn("if settings.BINANCE_PAY_API_SECRET:\n        if not verify", misc)
        self.assertIn("not settings.BINANCE_PAY_API_SECRET", misc)

    def test_access_tokens_and_admin_tokens_are_separated(self):
        sec = (BACKEND / "core" / "security.py").read_text()
        self.assertIn('payload.get("type") != "access"', sec)
        self.assertIn('"type": "admin_access"', sec)

    def test_submit_blocks_resubmission(self):
        self.assertIn('("payment_submitted", "under_review")', (EP / "orders.py").read_text())

    def test_rate_limit_registered_before_cors(self):
        main = (BACKEND / "main.py").read_text()
        self.assertLess(main.index("rate_limit_middleware)"), main.index("CORSMiddleware,"))

    def test_no_hardcoded_secrets_in_repo(self):
        pat = re.compile(r"(AKIA[0-9A-Z]{16}|-----BEGIN (RSA )?PRIVATE KEY-----|\b\d{8,10}:[A-Za-z0-9_-]{35}\b)")
        for f in list((ROOT / "video-store-backend").rglob("*")) + list((ROOT / "video-store-frontend" / "src").rglob("*")):
            if f.is_file() and f.suffix in (".py", ".ts", ".tsx", ".md", ".yaml", ".json") and "node_modules" not in f.parts:
                m = pat.search(f.read_text(errors="ignore"))
                self.assertIsNone(m, f"possible secret in {f}")


class FrontendStatic(unittest.TestCase):
    def test_jwt_refresh_wired(self):
        c = (FRONTEND / "api" / "client.ts").read_text()
        self.assertIn("/auth/refresh", c)
        self.assertIn("_retried", c)

    def test_expired_flag_in_types_and_badge(self):
        self.assertIn("expired?: boolean", (FRONTEND / "types" / "index.ts").read_text())
        self.assertIn("access.expired", (FRONTEND / "components" / "access" / "index.tsx").read_text())

    def test_order_status_types_cover_backend(self):
        be = (BACKEND / "schemas" / "__init__.py").read_text()
        block = re.search(r"OrderStatus = Literal\[(.*?)\]", be, re.S).group(1)
        be_vals = set(re.findall(r'"(\w+)"', block))
        fe = (FRONTEND / "types" / "index.ts").read_text()
        fe_block = re.search(r"export type OrderStatus =(.*?)\n\nexport", fe, re.S).group(1)
        fe_vals = set(re.findall(r"'(\w+)'", fe_block))
        self.assertEqual(be_vals - fe_vals, set(), "backend order statuses missing in frontend types")


class ValidationAndIntegrity(unittest.TestCase):
    def test_request_models_have_bounds(self):
        src = (BACKEND / "schemas" / "__init__.py").read_text()
        tree = ast.parse(src)
        wanted = {
            "TelegramAuthRequest": "init_data", "OrderCreateRequest": "content_id",
            "PaymentSubmitRequest": "user_note", "AdSessionStartRequest": "content_id",
            "AdSessionCompleteRequest": "server_token", "CouponValidateRequest": "order_amount_bdt",
            "SupportTicketRequest": "message",
        }
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in wanted]:
            line = next(ast.unparse(a) for a in cls.body
                        if isinstance(a, (ast.AnnAssign,)) and a.target.id == wanted[cls.name])
            self.assertIn("Field(", line, f"{cls.name}.{wanted[cls.name]} unbounded")
            self.assertTrue("max_length" in line or "le=" in line, f"{cls.name}.{wanted[cls.name]} no upper bound")

    def test_payment_submit_requires_proof(self):
        self.assertIn("transaction_hash or screenshot_url is required", (BACKEND / "schemas" / "__init__.py").read_text())

    def test_purchase_and_ads_check_content_state(self):
        self.assertIn('purchase_enabled", True', (EP / "orders.py").read_text())
        ads = (EP / "ads.py").read_text()
        self.assertIn('.get("is_published")', ads)

    def test_fulfillment_is_idempotent_and_records_coupon(self):
        f = (BACKEND / "services" / "fulfillment.py").read_text()
        self.assertIn('entitlement_id=f"ent_{order_id}"', f)
        self.assertIn("AlreadyExists", f)
        self.assertIn("record_coupon_usage", f)

    def test_package_and_video_access_share_expiry_rules(self):
        e = (BACKEND / "services" / "entitlement.py").read_text()
        rules = (BACKEND / "services" / "access_rules.py").read_text()
        # Phase 8 B-1: the expiry rules moved out of entitlement.py into one shared
        # pure module; video AND package checks must both go through it.
        self.assertIn("had_expired", rules)
        self.assertGreaterEqual(e.count("evaluate_access("), 2)
        self.assertIn('"array_contains"', e, "package entitlement must grant included videos")

    def test_every_env_example_key_is_a_setting(self):
        cfg = (BACKEND / "core" / "config.py").read_text()
        for line in (ROOT / "video-store-backend" / ".env.example").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                self.assertIn(line.split("=")[0].strip(), cfg)


class PureUnits(unittest.TestCase):
    def test_hmac_helper_fail_closed(self):
        import hashlib, hmac
        from app.core.webhook_utils import verify_hmac_sha256_hex, amount_covers
        body = b'{"a":1}'
        good = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_hmac_sha256_hex("s3cret", body, good))
        self.assertFalse(verify_hmac_sha256_hex("", body, good), "empty secret must reject")
        self.assertFalse(verify_hmac_sha256_hex("s3cret", body, ""))
        self.assertFalse(verify_hmac_sha256_hex("s3cret", body, "0" * 64))
        self.assertFalse(verify_hmac_sha256_hex("other", body, good))
        self.assertTrue(amount_covers(1.0, 1.0))
        self.assertFalse(amount_covers(1.0, 0.5))

    def test_rate_limiter(self):
        from app.core.rate_limit import SlidingWindowLimiter, match_rule
        lim = SlidingWindowLimiter()
        self.assertTrue(all(lim.check("k", 3, 60, now=t)[0] for t in (0, 1, 2)))
        ok, retry = lim.check("k", 3, 60, now=3)
        self.assertFalse(ok)
        self.assertGreater(retry, 0)
        self.assertTrue(lim.check("k", 3, 60, now=61)[0], "window must slide")
        self.assertTrue(lim.check("other", 3, 60, now=3)[0], "keys are independent")
        self.assertEqual(match_rule("/api/v1/admin/login", "POST")[:2], (5, 300))
        self.assertIsNotNone(match_rule("/api/v1/videos", "GET"))
        self.assertIsNone(match_rule("/health", "GET"))

    def test_fernet_roundtrip_with_ephemeral_key(self):
        from cryptography.fernet import Fernet
        f = Fernet(Fernet.generate_key())  # throwaway key, never stored
        self.assertEqual(f.decrypt(f.encrypt(b"https://x/y")), b"https://x/y")


if __name__ == "__main__":
    unittest.main(verbosity=2)
