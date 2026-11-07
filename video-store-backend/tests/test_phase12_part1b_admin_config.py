"""
Phase 12 / Part 1B — admin configuration structure.

  A. Config rules / schema  — pure logic of app.services.admin_config (always runs).
  B. Route contract         — AST inspection of endpoints/admin_config.py (always runs; FastAPI is
                              not needed): every route is admin-guarded, secrets never leave.
  C. Consistency            — the schema is derived from the modules that own the rules.
"""
import ast
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core import admin_roles as R  # noqa: E402
from app.services import admin_config as C  # noqa: E402
from app.services import payment_methods as PM  # noqa: E402
from app.services import ad_config as ADS  # noqa: E402
from app.services.source_types import SUPPORTED_SOURCE_TYPES  # noqa: E402

SRC = (BACKEND / "app" / "api" / "v1" / "endpoints" / "admin_config.py").read_text()
TREE = ast.parse(SRC)


class VideoRules(unittest.TestCase):
    ok = {"title": "A", "quality": "HD", "source_type": "direct_mp4", "category_ids": ["c1"],
          "primary_category_id": "c1", "price_bdt": 50, "has_source": True}

    def test_valid(self):
        self.assertEqual(C.video_problems(self.ok), [])

    def test_bad_values(self):
        for patch, frag in (({"title": " "}, "title"), ({"quality": "720p"}, "quality"),
                            ({"source_type": "youtube"}, "source_type"), ({"thumbnail_url": "http://x"}, "https"),
                            ({"primary_category_id": "zz"}, "primary_category_id"),
                            ({"category_ids": ["c1", "c1"]}, "duplicates"), ({"slug": "Bad Slug"}, "slug"),
                            ({"price_bdt": 0}, "price")):
            self.assertTrue(any(frag in p for p in C.video_problems({**self.ok, **patch})), patch)

    def test_free_video_may_cost_zero(self):
        self.assertEqual(C.video_problems({**self.ok, "price_bdt": 0, "is_free": True}), [])

    def test_cannot_publish_without_source(self):
        self.assertTrue(C.video_problems({**self.ok, "is_published": True, "has_source": False}))
        self.assertEqual(C.video_problems({**self.ok, "is_published": True}), [])

    def test_slugify(self):
        self.assertEqual(C.slugify("  Hello,  World! 2 "), "hello-world-2")
        self.assertEqual(C.slugify("!!!"), "")


class PackageRules(unittest.TestCase):
    ok = {"name": "P", "video_ids": ["a", "b"], "price_bdt": 80, "original_price_bdt": 100, "duration_type": "lifetime"}

    def test_valid_and_derived(self):
        self.assertEqual(C.package_problems(self.ok), [])
        d = C.package_derived(self.ok)
        self.assertEqual(d["video_count"], 2)
        self.assertEqual(d["discount_percentage"], 20.0)
        self.assertEqual(d["duration_hours"], 0)

    def test_problems(self):
        for patch, frag in (({"name": ""}, "name"), ({"video_ids": ["a", "a"]}, "duplicates"),
                            ({"video_ids": [str(i) for i in range(C.MAX_PACKAGE_VIDEOS + 1)]}, "at most"),
                            ({"duration_type": "custom", "duration_hours": 0}, "duration_hours"),
                            ({"duration_type": "weekly"}, "duration_type"),
                            ({"original_price_bdt": 10}, "original_price"), ({"price_bdt": 0}, "price"),
                            ({"is_published": True, "video_ids": []}, "empty")):
            self.assertTrue(any(frag in p for p in C.package_problems({**self.ok, **patch})), patch)

    def test_discount_never_negative_or_div_zero(self):
        self.assertEqual(C.package_derived({"video_ids": [], "price_bdt": 5, "original_price_bdt": 0}).get("discount_percentage", 0), 0)
        self.assertEqual(C.package_derived({"video_ids": [], "price_bdt": 120, "original_price_bdt": 100})["discount_percentage"], 0.0)

    def test_custom_duration_kept(self):
        self.assertNotIn("duration_hours", C.package_derived({**self.ok, "duration_type": "custom", "duration_hours": 48}))


class PaymentSettings(unittest.TestCase):
    def test_defaults_come_from_the_verifier(self):
        from app.services.payment_verification import DEFAULT_RETRY_LIMIT_24H, DEFAULT_VERIFY_MIN_INTERVAL_S
        v = C.payment_settings_view(None)
        self.assertEqual(v, {"payment_verify_min_interval_seconds": DEFAULT_VERIFY_MIN_INTERVAL_S,
                             "payment_retry_limit_24h": DEFAULT_RETRY_LIMIT_24H})

    def test_document_value_wins_and_garbage_falls_back(self):
        self.assertEqual(C.payment_settings_view({"payment_retry_limit_24h": 9})["payment_retry_limit_24h"], 9)
        self.assertEqual(C.payment_settings_view({"payment_retry_limit_24h": "x"})["payment_retry_limit_24h"],
                         C.PAYMENT_SETTING_BOUNDS["payment_retry_limit_24h"][0])

    def test_bounds(self):
        self.assertEqual(C.payment_setting_problems({"payment_retry_limit_24h": 0}), [])
        for bad in ({"payment_retry_limit_24h": -1}, {"payment_retry_limit_24h": 101}, {"payment_verify_min_interval_seconds": True},
                    {"payment_verify_min_interval_seconds": 5.5}, {"nope": 1}):
            self.assertTrue(C.payment_setting_problems(bad), bad)


class Readiness(unittest.TestCase):
    net = {"name": "Monetag", "type": "monetag", "is_enabled": True, "priority": 1, "zone_id": "123", "sdk_url": "https://x.example/sdk.js",
           "s2s_callback_supported": True, "placements": {"video_unlock": True, "package_unlock": False}}

    def test_ready_only_with_secret_and_config(self):
        r = C.ad_network_readiness("monetag", self.net, True)
        self.assertTrue(r["ready"], r["problems"])
        self.assertEqual(r["placements"], {"video_unlock": True, "package_unlock": False, "rewarded": False})
        self.assertFalse(C.ad_network_readiness("monetag", self.net, False)["ready"])
        self.assertTrue(any("not set" in p for p in C.ad_network_readiness("monetag", self.net, False)["problems"]))

    def test_unknown_provider_and_disabled(self):
        self.assertFalse(C.ad_network_readiness("x", {"type": "ghost"}, True)["ready"])
        self.assertFalse(C.ad_network_readiness("monetag", {**self.net, "is_enabled": False}, True)["ready"])

    def test_no_secret_value_in_result(self):
        r = C.ad_network_readiness("monetag", self.net, True)
        self.assertIsInstance(r["secret_configured"], bool)
        self.assertNotIn("secret", " ".join(k for k in r if k not in ("secret_setting", "secret_configured")))

    def test_binance_booleans_only(self):
        r = C.binance_readiness("k", "", "m")
        self.assertFalse(r["configured"])
        self.assertEqual(r["missing_settings"], ["BINANCE_PAY_API_SECRET"])
        self.assertEqual(set(r["credentials"].values()), {True, False})
        self.assertNotIn("'k'", str(r))
        self.assertNotIn("'m'", str(r))


class SchemaConsistency(unittest.TestCase):
    def test_enums_come_from_owning_modules(self):
        self.assertEqual(C.VIDEO_FIELDS["source_type"]["options"], list(SUPPORTED_SOURCE_TYPES))
        self.assertEqual(C.AD_NETWORK_FIELDS["placements"]["keys"], list(ADS.PLACEMENTS))
        self.assertEqual(C.PAYMENT_METHOD_FIELDS["type"]["options"], sorted(PM.METHOD_TYPES))
        self.assertEqual(C.PAYMENT_METHOD_FIELDS["payment_timeout_minutes"]["max"], PM.MAX_TIMEOUT_MIN)
        self.assertEqual(C.VIDEO_FIELDS["ads_required"]["default"], ADS.DEFAULT_ADS_REQUIRED)

    def test_video_quality_matches_response_schema(self):
        src = (BACKEND / "app" / "schemas" / "__init__.py").read_text()
        for q in C.VIDEO_QUALITIES:
            self.assertIn(f'"{q}"', src.split("VideoQuality")[1].split("\n")[0])

    def test_source_url_is_write_only(self):
        self.assertTrue(C.VIDEO_FIELDS["source_url"]["write_only"])

    def test_payment_fields_cover_admin_api_fields(self):
        ep = (BACKEND / "app" / "api" / "v1" / "endpoints" / "admin_payment_methods.py").read_text()
        fields = ast.literal_eval(ep.split("_FIELDS = ")[1].split("\n)\n")[0] + "\n)")
        self.assertEqual(set(fields), set(C.PAYMENT_METHOD_FIELDS))

    def test_schema_respects_permissions(self):
        mod = C.schema_for(R.permissions_for(R.MODERATOR))["modules"]
        self.assertTrue(mod["videos"]["can_view"] and not mod["videos"]["can_manage"])
        self.assertFalse(mod["ads"]["can_view"] or mod["payments"]["can_view"])
        adm = C.schema_for(R.permissions_for(R.ADMIN))["modules"]
        self.assertTrue(adm["videos"]["can_manage"])
        self.assertFalse(adm["ads"]["can_manage"] or adm["payments"]["can_manage"])   # super-admin only
        sup = C.schema_for(R.permissions_for(R.SUPER_ADMIN))["modules"]
        self.assertTrue(all(m["can_manage"] for m in sup.values()))

    def test_module_permissions_exist(self):
        for m in C.MODULES.values():
            self.assertIn(m["view"], R.ALL_PERMISSIONS)
            self.assertIn(m["manage"], R.ALL_PERMISSIONS)


class RouteContract(unittest.TestCase):
    def routes(self):
        out = []
        for fn in ast.walk(TREE):
            if isinstance(fn, ast.AsyncFunctionDef):
                for dec in fn.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name) \
                            and dec.func.value.id == "router":
                        out.append((fn, dec))
        return out

    def test_every_route_is_admin_guarded(self):
        rs = self.routes()
        self.assertEqual(len(rs), 16)
        for fn, dec in rs:
            seg = ast.get_source_segment(SRC, dec) + ast.unparse(fn.args)
            self.assertTrue("require_permission(Perm." in seg or "get_admin_context" in seg, fn.name)

    def test_writes_need_manage_permission(self):
        for fn, dec in self.routes():
            if dec.func.attr in ("post", "put", "patch"):
                seg = ast.get_source_segment(SRC, dec)
                self.assertTrue(any(p in seg for p in ("VIDEOS_MANAGE", "ADS_MANAGE", "PAYMENT_METHODS_MANAGE")), fn.name)
                self.assertNotIn("VIEW", seg, fn.name)

    def test_writes_are_audited(self):
        for fn, dec in self.routes():
            if dec.func.attr in ("post", "put", "patch"):
                self.assertIn("audit_log(", ast.get_source_segment(SRC, fn), fn.name)

    def test_source_url_never_returned(self):
        view = next(f for f in ast.walk(TREE) if isinstance(f, ast.FunctionDef) and f.name == "_video_view")
        body = ast.get_source_segment(SRC, view)
        self.assertNotIn('"source_url_encrypted":', body)
        self.assertNotIn('d.get("source_url_encrypted")', body.replace("bool(d.get(\"source_url_encrypted\"))", ""))
        self.assertIn("has_source", body)
        self.assertNotIn("source_url", ",".join(_VIDEO_WRITE_KEYS()))

    def test_no_route_shadows_existing_admin_paths(self):
        used = []
        for fn, dec in self.routes():
            used.append((dec.func.attr, dec.args[0].value))
        self.assertEqual(len(used), len(set(used)))
        for existing in (BACKEND / "app" / "api" / "v1" / "endpoints").glob("admin*.py"):
            if existing.name == "admin_config.py":
                continue
            t = ast.parse(existing.read_text())
            for fn in ast.walk(t):
                if isinstance(fn, ast.AsyncFunctionDef):
                    for dec in fn.decorator_list:
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args \
                                and isinstance(dec.args[0], ast.Constant) and dec.func.attr in ("get", "post", "put", "patch", "delete"):
                            self.assertNotIn((dec.func.attr, dec.args[0].value), used, existing.name)

    def test_router_registered_and_existing_routers_kept(self):
        r = (BACKEND / "app" / "api" / "v1" / "router.py").read_text()
        for name in ("auth", "config", "videos", "packages", "orders", "ads", "misc", "admin_auth", "admin", "admin_payment_methods", "admin_config"):
            self.assertIn(f"include_router({name}.router)", r)

    def test_no_new_collection(self):
        self.assertNotIn('collection("', SRC)          # only the Col.* constants that already exist
        used = {n.attr for n in ast.walk(TREE) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "Col"}
        fb = (BACKEND / "app" / "db" / "firebase.py").read_text()
        for name in used:
            self.assertIn(f"    {name}", fb)


def _VIDEO_WRITE_KEYS():
    return [k for k, spec in C.VIDEO_FIELDS.items() if not spec.get("write_only") and k != "slug"]


if __name__ == "__main__":
    unittest.main()
