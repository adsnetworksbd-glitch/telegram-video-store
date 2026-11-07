"""
Phase 7 — offline integration checks (NO network, NO Firestore, NO FastAPI).

What these really execute:
  * the real Pydantic response models (app.schemas) are imported and compared
    field-by-field (names + nullability + enum values) with the frontend
    TypeScript interfaces in src/types/index.ts;
  * query-parameter / request-body names used by src/api/index.ts are compared
    with the real backend endpoint signatures (AST);
  * the pure mappers (app.services.mappers) are run against Firestore-shaped dicts.

What they do NOT do: start FastAPI, call Firestore, or run an endpoint.
"""
import ast
import json
import re
import sys
import types
import typing
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "video-store-backend"
FRONTEND = ROOT / "video-store-frontend" / "src"
EP = BACKEND_ROOT / "app" / "api" / "v1" / "endpoints"
sys.path.insert(0, str(BACKEND_ROOT))

from app import schemas as S  # noqa: E402  (pydantic only)
from app.services import mappers  # noqa: E402


# ─── TypeScript interface parser (small, purpose-built) ───────────────────────
def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//.*$", "", src)


def parse_ts_interfaces(path: Path) -> dict:
    text = _strip_comments(path.read_text())
    out = {}
    for m in re.finditer(r"export interface (\w+)(?:\s+extends\s+(\w+))?\s*\{(.*?)\n\}", text, flags=re.S):
        name, parent, body = m.group(1), m.group(2), m.group(3)
        fields = {}
        for fm in re.finditer(r"(?m)^\s*(\w+)(\?)?:\s*(.+?)\s*$", body):
            fields[fm.group(1)] = {"optional": bool(fm.group(2)), "type": fm.group(3)}
        out[name] = {"extends": parent, "fields": fields}
    return out


def ts_fields(ifaces: dict, name: str) -> dict:
    node = ifaces[name]
    fields = ts_fields(ifaces, node["extends"]) if node["extends"] else {}
    return {**fields, **node["fields"]}


def py_nullable(annotation) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return type(None) in typing.get_args(annotation)
    return annotation is type(None)


PAIRS = [
    "UserProfile", "HomepageSection", "AppConfig", "Video", "VideoDetail", "Category",
    "Package", "PackageDetail", "AccessStatus", "AvailableMethods", "SourceAccess",
    "Entitlement", "Order", "Payment", "PaymentMethod", "PaymentDetails",
    "AdNetworkConfig", "AdSession", "CouponValidation", "ReferralInfo", "Referral",
    "Transaction", "Notification",
]


class SchemaMatchesTypeScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = parse_ts_interfaces(FRONTEND / "types" / "index.ts")

    def test_parser_sanity(self):
        self.assertGreater(len(self.ts), 20)
        self.assertIn("created_at", ts_fields(self.ts, "VideoDetail"))  # inherited

    def test_field_names_match_both_ways(self):
        problems = []
        for name in PAIRS:
            model = getattr(S, name)
            py = set(model.model_fields)
            ts = ts_fields(self.ts, name)
            ts_required = {k for k, v in ts.items() if not v["optional"]}
            ts_all = set(ts)
            if ts_required - py:
                problems.append(f"{name}: TS requires fields the backend never sends: {sorted(ts_required - py)}")
            if py - ts_all:
                problems.append(f"{name}: backend sends fields missing from TS: {sorted(py - ts_all)}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_nullability_agrees(self):
        problems = []
        for name in PAIRS:
            model = getattr(S, name)
            for k, info in ts_fields(self.ts, name).items():
                if k not in model.model_fields:
                    continue
                ts_null = "| null" in info["type"] or info["type"].strip() == "null"
                py_null = py_nullable(model.model_fields[k].annotation)
                if info["optional"]:
                    continue
                if ts_null != py_null:
                    problems.append(f"{name}.{k}: TS nullable={ts_null} but backend nullable={py_null}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_literal_values_match_ts_unions(self):
        def ts_union(name):
            text = _strip_comments((FRONTEND / "types" / "index.ts").read_text())
            m = re.search(rf"export type {name}\s*=\s*([^\n]*(?:\n\s*\|[^\n]*)*)", text)
            return set(re.findall(r"'([^']+)'", m.group(1))) if m else set()

        pairs = {
            "VideoQuality": S.VideoQuality, "SourceType": S.SourceType,
            "AccessSource": S.AccessSource, "EntitlementStatus": S.EntitlementStatus,
            "OrderStatus": S.OrderStatus,
        }
        for ts_name, lit in pairs.items():
            self.assertEqual(ts_union(ts_name), set(typing.get_args(lit)), ts_name)

    def test_envelope_keys(self):
        # Shapes api/index.ts relies on.
        self.assertEqual(set(S.VideoListResponse.model_fields), {"items", "total", "page", "has_more"})
        self.assertEqual(set(S.PackageListResponse.model_fields), {"items", "total", "page", "has_more"})
        self.assertEqual(set(S.CategoryListResponse.model_fields), {"categories"})
        self.assertEqual(set(S.CategoryDetailResponse.model_fields), {"category", "videos", "total"})
        self.assertEqual(set(S.PaymentMethodListResponse.model_fields), {"methods"})
        self.assertEqual(set(S.NotificationListResponse.model_fields), {"notifications", "unread_count"})
        self.assertEqual(set(S.FAQListResponse.model_fields), {"faqs"})
        self.assertEqual(set(S.SearchResponse.model_fields), {"videos", "packages", "total"})
        # Old contract {order, payment} is preserved: those stay the only REQUIRED
        # fields; the Phase 10 additions are optional with defaults (additive only).
        od = S.OrderDetailResponse.model_fields
        self.assertEqual({k for k, f in od.items() if f.is_required()}, {"order", "payment"})
        self.assertEqual(set(od), {"order", "payment", "details", "timeline", "retry"})
        self.assertEqual(set(S.OrderCreateResponse.model_fields),
                         {"order_id", "final_bdt", "final_usdt", "usdt_rate", "expires_at", "payment_details"})
        self.assertEqual(set(S.PaymentSubmitResponse.model_fields), {"status", "message"})
        self.assertEqual(set(S.TokenResponse.model_fields), {"access_token", "user"})


# ─── Query params / bodies used by the frontend vs real endpoint signatures ───
def backend_signatures() -> dict:
    """(METHOD, normalized_path) -> {"params": set(query names), "body": model or None}"""
    sigs = {}
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
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and getattr(dec.func.value, "id", "") == "router"
                        and dec.func.attr in ("get", "post", "put", "patch", "delete")):
                    continue
                path = re.sub(r"\{[^}]+\}", "{}", prefix + dec.args[0].value)
                params, body = set(), None
                path_names = set(re.findall(r"\{([^}]+)\}", prefix + dec.args[0].value))
                args = node.args.args
                defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
                for a, d in zip(args, defaults):
                    if a.arg in path_names or a.arg in ("user_id", "request"):
                        continue
                    if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "Query":
                        alias = next((k.value.value for k in d.keywords if k.arg == "alias"), None)
                        params.add(alias or a.arg)
                    elif d is None and isinstance(a.annotation, ast.Name):
                        body = a.annotation.id
                sigs[(dec.func.attr.upper(), path)] = {"params": params, "body": body}
    return sigs


class RequestsMatchBackendSignatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (FRONTEND / "api" / "index.ts").read_text()
        cls.sigs = backend_signatures()

    def test_query_params_exist_on_backend(self):
        pattern = re.compile(
            r"\w+:\s*\((?:[^()]*?)params\?:\s*\{([^}]*)\}\)\s*=>\s*api\.(get|post)<[\s\S]*?>\(\s*([`'])(.+?)\3"
        )
        checked, problems = 0, []
        for m in pattern.finditer(self.src):
            names = set(re.findall(r"(\w+)\??:", m.group(1)))
            path = re.sub(r"\$\{[^}]+\}", "{}", m.group(4))
            sig = self.sigs.get((m.group(2).upper(), path))
            self.assertIsNotNone(sig, f"no backend route for {m.group(2)} {path}")
            checked += 1
            missing = names - sig["params"]
            if missing:
                problems.append(f"{path}: frontend sends unknown query params {sorted(missing)}")
        self.assertGreaterEqual(checked, 9, "parser found too few param-taking calls")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_request_body_keys_match_backend_models(self):
        pattern = re.compile(r"(\w+):\s*\((?:[^()]*?)body:\s*\{([^}]*)\}\)")
        models = {
            "create": S.OrderCreateRequest, "submit": S.PaymentSubmitRequest,
            "validate": S.CouponValidateRequest, "startSession": S.AdSessionStartRequest,
            "submitTicket": S.SupportTicketRequest,
        }
        seen = set()
        for m in pattern.finditer(self.src):
            fn = m.group(1)
            if fn not in models:
                continue
            seen.add(fn)
            ts_keys = set(re.findall(r"(\w+)\??:", m.group(2)))
            self.assertEqual(ts_keys, set(models[fn].model_fields), f"body of {fn}")
        self.assertEqual(seen, set(models))

    def test_required_backend_fields_are_sent(self):
        # PaymentSubmitRequest needs hash OR screenshot: frontend sends hash.
        with self.assertRaises(Exception):
            S.PaymentSubmitRequest(user_note="x")
        S.PaymentSubmitRequest(transaction_hash="0xabc12345")


# ─── Pure mappers ─────────────────────────────────────────────────────────────
class MapperBehaviour(unittest.TestCase):
    def test_missing_config_document_gives_documented_defaults(self):
        c = mappers.build_app_config(None)
        self.assertEqual(c.app_name, "Video Store")
        self.assertEqual(c.usdt_to_bdt_rate, 115.0)
        self.assertTrue(c.referral_enabled)
        self.assertFalse(c.wallet_enabled)
        self.assertFalse(c.maintenance_mode)
        self.assertIsNone(c.support_url)

    def test_partial_document_keeps_admin_values_and_fills_rest(self):
        c = mappers.build_app_config({
            "app_name": "My Store", "usdt_to_bdt_rate": 121.5, "maintenance_mode": True,
            "homepage_announcement": "Sale!", "homepage_announcement_url": "https://t.me/x",
            "support_url": "https://t.me/support", "unknown_key": 1,
        })
        self.assertEqual(c.app_name, "My Store")
        self.assertEqual(c.usdt_to_bdt_rate, 121.5)
        self.assertTrue(c.maintenance_mode)
        self.assertEqual(c.maintenance_message, "")          # previously a 500
        self.assertEqual(c.homepage_announcement_url, "https://t.me/x")
        self.assertEqual(c.support_url, "https://t.me/support")

    def test_malformed_field_is_dropped_not_fatal(self):
        c = mappers.build_app_config({"usdt_to_bdt_rate": "abc", "maintenance_mode": "maybe", "app_name": "OK"})
        self.assertEqual(c.usdt_to_bdt_rate, 115.0)
        self.assertFalse(c.maintenance_mode)
        self.assertEqual(c.app_name, "OK")

    def test_config_json_has_every_frontend_field(self):
        dumped = mappers.build_app_config({}).model_dump()
        ts = ts_fields(parse_ts_interfaces(FRONTEND / "types" / "index.ts"), "AppConfig")
        self.assertEqual(set(ts), set(dumped))

    def test_category_missing_fields(self):
        c = mappers.build_category("c1", {"name": "Action"})
        self.assertEqual((c.id, c.name, c.slug, c.video_count, c.display_order), ("c1", "Action", "c1", 0, 0))
        self.assertIsNone(c.description)

    def test_category_bad_value_and_full_doc(self):
        c = mappers.build_category("c2", {"name": "Drama", "slug": "drama", "thumbnail_url": "https://x/y.jpg",
                                          "description": "d", "video_count": "many", "display_order": 3})
        self.assertEqual((c.slug, c.video_count, c.display_order, c.description), ("drama", 0, 3, "d"))

    def test_category_none_doc(self):
        self.assertEqual(mappers.build_category("c3", None).slug, "c3")


# ─── Static guards for code that needs FastAPI/Firestore to actually run ──────
class StaticGuards(unittest.TestCase):
    def test_missing_bearer_is_401_not_403(self):
        src = (BACKEND_ROOT / "app" / "core" / "deps.py").read_text()
        self.assertIn("HTTPBearer(auto_error=False)", src)
        self.assertRegex(src, r"credentials is None[\s\S]{0,200}HTTP_401_UNAUTHORIZED")

    def test_order_expiry_only_touches_awaiting_payment(self):
        src = (EP / "orders.py").read_text()
        m = re.search(r"def _effective_order_status[\s\S]*?return st\n", src)
        self.assertIsNotNone(m)
        self.assertIn('st == "awaiting_payment"', m.group(0))

    def test_frontend_has_no_hardcoded_production_api_host(self):
        client = (FRONTEND / "api" / "client.ts").read_text()
        self.assertNotRegex(client, r"https://api\.videostore\.app")
        self.assertIn("apiConfigProblem", client)

    def test_no_backend_secrets_in_frontend(self):
        bad = re.compile(r"(PRIVATE KEY|firebase-service-account|BINANCE_PAY_API_SECRET|MONETAG_CALLBACK_SECRET|"
                         r"SOURCE_URL_ENCRYPTION_KEY|ADMIN_PASSWORD_HASH|TELEGRAM_BOT_TOKEN)")
        hits = []
        for p in (FRONTEND.parent).rglob("*"):
            if p.is_file() and "node_modules" not in p.parts and p.suffix in {".ts", ".tsx", ".json", ".js", ".env", ""} \
                    and p.name not in {"package-lock.json"}:
                try:
                    if bad.search(p.read_text()):
                        hits.append(str(p.relative_to(ROOT)))
                except (UnicodeDecodeError, OSError):
                    pass
        self.assertEqual(hits, [])


class FirestoreIndexFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((BACKEND_ROOT / "firestore.indexes.json").read_text())

    def _has(self, collection, *fields):
        want = [tuple(f) for f in fields]
        for ix in self.data["indexes"]:
            got = [(f["fieldPath"], f.get("order") or f.get("arrayConfig")) for f in ix["fields"]]
            if ix["collectionGroup"] == collection and got == want:
                return True
        return False

    def test_well_formed_and_unique(self):
        sigs = [json.dumps(i, sort_keys=True) for i in self.data["indexes"]]
        self.assertEqual(len(sigs), len(set(sigs)))
        for ix in self.data["indexes"]:
            self.assertEqual(ix["queryScope"], "COLLECTION")
            self.assertGreaterEqual(len(ix["fields"]), 2)

    def test_indexes_for_queries_that_were_missing(self):
        A, D, C = "ASCENDING", "DESCENDING", "CONTAINS"
        self.assertTrue(self._has("videos", ("is_published", A), ("created_at", D)))
        self.assertTrue(self._has("videos", ("is_published", A), ("view_count", D)))
        self.assertTrue(self._has("categories", ("is_visible", A), ("display_order", A)))
        self.assertTrue(self._has("packages", ("is_published", A), ("display_order", A)))
        self.assertTrue(self._has("payment_methods", ("is_enabled", A), ("display_order", A)))
        self.assertTrue(self._has("ad_networks", ("is_enabled", A), ("priority", A)))
        self.assertTrue(self._has("faq", ("is_visible", A), ("display_order", A)))
        self.assertTrue(self._has("videos", ("is_published", A), ("category_ids", C), ("created_at", D)))


if __name__ == "__main__":
    unittest.main()
