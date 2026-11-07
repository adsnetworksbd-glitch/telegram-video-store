"""
Phase 12 / Part 1C — coupons, referral, homepage, app settings, notifications, user access & expiry.
Pure rules (app.services.admin_settings) + AST contract of endpoints/admin_manage.py. No FastAPI needed.
"""
import ast
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core import admin_roles as R  # noqa: E402
from app.services import admin_config as C  # noqa: E402
from app.services import admin_settings as S  # noqa: E402
from app.services.access_rules import entitlement_state  # noqa: E402

EP = BACKEND / "app" / "api" / "v1" / "endpoints"
SRC = (EP / "admin_manage.py").read_text()
TREE = ast.parse(SRC)
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


class Coupons(unittest.TestCase):
    ok = {"code": "SAVE10", "discount_type": "percentage", "discount_value": 10, "max_discount_bdt": 50,
          "applicable_to": "all", "applicable_ids": [], "usage_limit": 100, "used_count": 3}

    def test_valid(self):
        self.assertEqual(S.coupon_problems(self.ok), [])
        self.assertEqual(S.coupon_problems({**self.ok, "discount_type": "fixed_bdt", "discount_value": 40, "max_discount_bdt": None}), [])

    def test_problems(self):
        for patch, frag in (({"code": "a b"}, "code"), ({"code": "AB"}, "code"), ({"discount_type": "bogo"}, "discount_type"),
                            ({"discount_value": 0}, "discount_value"), ({"discount_value": 101}, "100"),
                            ({"discount_type": "fixed_bdt", "discount_value": 5}, "max_discount"),
                            ({"applicable_to": "videos"}, "applicable_ids is required"),
                            ({"applicable_ids": ["v1"]}, "must be empty"),
                            ({"applicable_to": "videos", "applicable_ids": ["a", "a"]}, "duplicates"),
                            ({"applicable_to": "x"}, "applicable_to"),
                            ({"valid_from": NOW, "valid_until": NOW}, "valid_until"),
                            ({"usage_limit": 2}, "usage_limit")):
            self.assertTrue(any(frag in p for p in S.coupon_problems({**self.ok, **patch})), patch)

    def test_code_normalised_like_validator(self):
        self.assertEqual(S.normalize_code("  save10 "), "SAVE10")

    def test_enums_match_coupon_service(self):
        src = (BACKEND / "app" / "services" / "coupon.py").read_text()
        for v in ("percentage", "fixed_bdt", "videos", "packages"):
            self.assertIn(f'"{v}"', src)


class Referral(unittest.TestCase):
    def test_defaults_match_referral_service(self):
        src = (BACKEND / "app" / "services" / "referral.py").read_text()
        self.assertIn('cfg.get("referral_enabled", False)', src)
        self.assertIn('cfg.get("referral_fraud_cooldown_hours", 48)', src)
        self.assertIn('cfg.get("referral_reward_amount", 100)', src)
        self.assertIn('cfg.get("referral_coupon_valid_days", 7)', src)       # previous fixed 7 days is the default
        v = S.referral_settings_view(None)
        self.assertEqual(v, S.REFERRAL_DEFAULTS)

    def test_view_prefers_document(self):
        self.assertEqual(S.referral_settings_view({"referral_enabled": True, "referral_reward_amount": 50})["referral_reward_amount"], 50)

    def test_validation(self):
        self.assertEqual(S.referral_problems({"referral_enabled": True, "referral_reward_amount": 75.5,
                                              "referral_fraud_cooldown_hours": 0, "referral_coupon_valid_days": 30}), [])
        for bad in ({"referral_reward_type": "cash"}, {"referral_reward_amount": 0}, {"referral_enabled": "yes"},
                    {"referral_fraud_cooldown_hours": 1.5}, {"referral_coupon_valid_days": 0},
                    {"referral_coupon_valid_days": True}, {"nope": 1}):
            self.assertTrue(S.referral_problems(bad), bad)

    def test_only_implemented_reward_offered(self):
        self.assertEqual(S.REFERRAL_FIELDS["referral_reward_type"]["options"], ["coupon"])

    def test_coupon_validity_uses_setting_safely(self):
        src = (BACKEND / "app" / "services" / "referral.py").read_text()
        self.assertIn("valid_days", src.split("_create_referral_coupon(")[2])


class Homepage(unittest.TestCase):
    def test_section_ids_match_frontend(self):
        fe = (BACKEND.parent / "video-store-frontend" / "src" / "pages" / "Home" / "index.tsx").read_text()
        for sid in S.HOMEPAGE_SECTION_IDS:
            self.assertIn(sid, fe)
        seed = (BACKEND / "app" / "api" / "v1" / "endpoints" / "config.py").read_text()
        for sid in S.HOMEPAGE_SECTION_IDS[:-1]:
            self.assertIn(f'id="{sid}"', seed)

    def test_sections(self):
        ok = [{"id": "featured_videos", "label": "A"}, {"id": "latest_videos", "label": "B", "order": 9}]
        self.assertEqual(S.section_problems(ok), [])
        n = S.normalize_sections(ok)
        self.assertEqual([x["order"] for x in n], [1, 9])
        self.assertEqual(set(n[0]), {"id", "label", "enabled", "order"})
        self.assertTrue(S.section_problems([{"id": "x", "label": "A"}]))
        self.assertTrue(S.section_problems([*ok, ok[0]]))
        self.assertTrue(S.section_problems([{"id": "latest_videos", "label": " "}]))

    def test_banner_rules(self):
        b = {"id": "b1", "image_url": "https://x/i.png", "link_type": "video", "link_id": "v1"}
        self.assertEqual(S.banner_problems([b]), [])
        for patch, frag in (({"image_url": "http://x"}, "image_url"), ({"link_id": None}, "link_id"),
                            ({"link_type": "url"}, "link_url"), ({"link_type": "zzz"}, "link_type"),
                            ({"id": "a b"}, "id"), ({"starts_at": NOW, "ends_at": NOW}, "ends_at")):
            self.assertTrue(any(frag in p for p in S.banner_problems([{**b, **patch}])), patch)
        self.assertTrue(S.banner_problems([b, b]))
        self.assertTrue(S.banner_problems([{**b, "id": str(i)} for i in range(S.MAX_BANNERS + 1)]))

    def test_public_banners_filtered_sorted_and_safe(self):
        raw = [
            {"id": "b", "image_url": "https://x/b.png", "order": 2},
            {"id": "a", "image_url": "https://x/a.png", "order": 1, "link_type": "url", "link_url": "https://y"},
            {"id": "off", "image_url": "https://x/o.png", "enabled": False},
            {"id": "future", "image_url": "https://x/f.png", "starts_at": NOW + timedelta(hours=1)},
            {"id": "past", "image_url": "https://x/p.png", "ends_at": NOW},
            {"id": "bad", "image_url": "http://x/p.png"},
            {"id": "evil", "image_url": "https://x/e.png", "order": 3, "link_type": "url", "link_url": "javascript:alert(1)"},
            "junk", None,
        ]
        out = S.active_banners(raw, NOW)
        self.assertEqual([b["id"] for b in out], ["a", "b", "evil"])
        self.assertIsNone(out[2]["link_url"])
        self.assertEqual(out[0]["link_url"], "https://y")
        self.assertEqual(S.active_banners(None, NOW), [])
        from app.schemas import HomepageBanner, HomepageConfig
        [HomepageBanner(**b) for b in out]
        self.assertEqual(HomepageConfig(sections=[]).banners, [])      # old payloads stay valid

    def test_public_homepage_route_still_returns_sections(self):
        src = (EP / "config.py").read_text()
        self.assertIn("response_model=HomepageConfig", src)
        self.assertIn("_DEFAULT_SECTIONS", src)


class AppSettings(unittest.TestCase):
    def test_valid_and_clean(self):
        ch = S.clean_app_settings({"app_name": " Store ", "support_username": "@help_bot", "support_url": " ", "usdt_to_bdt_rate": 121.5,
                                   "maintenance_mode": True})
        self.assertEqual(ch["app_name"], "Store")
        self.assertEqual(ch["support_username"], "help_bot")
        self.assertIsNone(ch["support_url"])
        self.assertEqual(S.app_setting_problems(ch), [])

    def test_problems(self):
        for bad in ({"usdt_to_bdt_rate": 0}, {"usdt_to_bdt_rate": -3}, {"usdt_to_bdt_rate": True}, {"usdt_to_bdt_rate": 10_001},
                    {"maintenance_mode": "on"}, {"app_name": None}, {"app_name": ""}, {"terms_url": "http://t"},
                    {"support_username": "ab"}, {"currency_display": "X"}, {"unknown": 1}, {"app_logo_url": "ftp://x"}):
            self.assertTrue(S.app_setting_problems(S.clean_app_settings(bad)), bad)

    def test_nullable_can_clear(self):
        self.assertEqual(S.app_setting_problems({"terms_url": None, "app_logo_url": None, "support_username": None}), [])

    def test_fields_cover_public_config(self):
        from app.services.mappers import APP_CONFIG_DEFAULTS
        for k in APP_CONFIG_DEFAULTS:
            if k not in ("homepage_announcement", "homepage_announcement_url", "referral_enabled"):
                self.assertIn(k, S.APP_SETTING_FIELDS)


class Notifications(unittest.TestCase):
    ok = {"target": "all", "title": "Hi", "body": "Sale", "type": "promo"}

    def test_valid(self):
        self.assertEqual(S.notification_problems(self.ok), [])
        self.assertEqual(S.notification_problems({**self.ok, "target": "user", "user_id": "1",
                                                  "action_type": "open_video", "action_id": "v1"}), [])

    def test_problems(self):
        for patch in ({"target": "some"}, {"target": "user"}, {"user_id": "5"}, {"type": "purchase_success"},
                      {"title": " "}, {"action_type": "open_video"}, {"action_type": "open_x", "action_id": "1"},
                      {"action_type": "open_order", "action_id": "1"}):
            self.assertTrue(S.notification_problems({**self.ok, **patch}), patch)

    def test_actions_match_frontend(self):
        fe = (BACKEND.parent / "video-store-frontend" / "src" / "pages" / "Notifications" / "index.tsx").read_text()
        for a in S.NOTIFICATION_ACTIONS:
            self.assertIn(a, fe)


class AccessExpiry(unittest.TestCase):
    base = {"status": "active", "is_lifetime": False, "expires_at": NOW + timedelta(hours=10), "user_id": "u"}

    def test_extend_adds_to_current_expiry(self):
        self.assertEqual(S.extend_expiry(self.base, NOW, hours=5)["expires_at"], NOW + timedelta(hours=15))

    def test_extend_expired_counts_from_now(self):
        e = {**self.base, "expires_at": NOW - timedelta(days=3)}
        self.assertEqual(entitlement_state(e, NOW), "expired")
        ch = S.extend_expiry(e, NOW, hours=24)
        self.assertEqual(ch["expires_at"], NOW + timedelta(hours=24))
        self.assertEqual(entitlement_state({**e, **ch}, NOW), "active")

    def test_lifetime(self):
        ch = S.extend_expiry(self.base, NOW, lifetime=True)
        self.assertEqual(ch, {"is_lifetime": True, "expires_at": None})
        self.assertEqual(entitlement_state({**self.base, **ch}, NOW), "active")

    def test_refusals(self):
        for ent, kw in (({**self.base, "status": "revoked"}, {"hours": 1}), ({**self.base, "is_lifetime": True}, {"hours": 1}),
                        (self.base, {}), (self.base, {"hours": 1, "lifetime": True}), (self.base, {"hours": 0}),
                        (self.base, {"hours": True}), (self.base, {"hours": S.MAX_DURATION_HOURS + 1})):
            with self.assertRaises(ValueError):
                S.extend_expiry(ent, NOW, **kw)

    def test_naive_expiry_handled(self):
        e = {**self.base, "expires_at": datetime(2026, 11, 5, 14, 0)}
        self.assertEqual(S.extend_expiry(e, NOW, hours=1)["expires_at"], datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc))

    def test_admin_view_state(self):
        v = S.entitlement_admin_view("e1", {**self.base, "access_source": "admin_grant"}, NOW)
        self.assertEqual((v["id"], v["state"], v["access_source"]), ("e1", "active", "admin_grant"))
        self.assertEqual(S.entitlement_admin_view("e", {**self.base, "status": "revoked"}, NOW)["state"], "revoked")


class Schema(unittest.TestCase):
    def test_modules_registered_with_valid_permissions(self):
        for k in ("coupons", "referral", "homepage", "settings", "notifications", "access"):
            m = C.MODULES[k]
            self.assertIn(m["view"], R.ALL_PERMISSIONS)
            self.assertIn(m["manage"], R.ALL_PERMISSIONS)
        sch = C.schema_for(R.permissions_for(R.SUPER_ADMIN))["modules"]
        self.assertTrue(all(m["can_manage"] for m in sch.values()))
        self.assertEqual(C.schema_for(frozenset())["version"], "12.1d")

    def test_role_visibility(self):
        adm = C.schema_for(R.permissions_for(R.ADMIN))["modules"]
        self.assertTrue(adm["coupons"]["can_manage"] and adm["notifications"]["can_manage"] and adm["access"]["can_manage"])
        self.assertFalse(adm["settings"]["can_manage"] or adm["homepage"]["can_manage"] or adm["referral"]["can_manage"])
        mod = C.schema_for(R.permissions_for(R.MODERATOR))["modules"]
        self.assertTrue(mod["access"]["can_view"] and not mod["access"]["can_manage"])
        self.assertFalse(mod["coupons"]["can_view"] or mod["notifications"]["can_view"])


class RouteContract(unittest.TestCase):
    def routes(self):
        out = []
        for fn in ast.walk(TREE):
            if isinstance(fn, ast.AsyncFunctionDef):
                for dec in fn.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and getattr(dec.func.value, "id", "") == "router":
                        out.append((fn, dec))
        return out

    def test_all_guarded_writes_manage_and_audited(self):
        rs = self.routes()
        self.assertEqual(len(rs), 21)
        for fn, dec in rs:
            seg = ast.get_source_segment(SRC, dec)
            self.assertIn("require_permission(Perm.", seg, fn.name)
            if dec.func.attr in ("post", "put", "patch"):
                self.assertIn("audit_log(", ast.get_source_segment(SRC, fn), fn.name)
                self.assertTrue(any(p in seg for p in ("COUPONS_MANAGE", "SETTINGS_MANAGE", "NOTIFICATIONS_SEND", "USERS_MANAGE")), fn.name)

    def test_no_clash_with_other_admin_routes(self):
        used = {(d.func.attr, d.args[0].value) for _, d in self.routes()}
        self.assertEqual(len(used), len(self.routes()))
        for f in EP.glob("admin*.py"):
            if f.name == "admin_manage.py":
                continue
            for fn in ast.walk(ast.parse(f.read_text())):
                if isinstance(fn, ast.AsyncFunctionDef):
                    for dec in fn.decorator_list:
                        if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.func, ast.Attribute):
                            self.assertNotIn((dec.func.attr, dec.args[0].value), used, f.name)

    def test_registered_and_no_new_collection(self):
        r = (BACKEND / "app" / "api" / "v1" / "router.py").read_text()
        for n in ("admin", "admin_auth", "admin_payment_methods", "admin_config", "admin_manage"):
            self.assertIn(f"include_router({n}.router)", r)
        self.assertNotIn('collection("', SRC)
        fb = (BACKEND / "app" / "db" / "firebase.py").read_text()
        for n in {a.attr for a in ast.walk(TREE) if isinstance(a, ast.Attribute) and getattr(a.value, "id", "") == "Col"}:
            self.assertIn(f"    {n}", fb)

    def test_broadcast_is_bounded_and_skips_banned(self):
        self.assertIn("MAX_BROADCAST_USERS", SRC)
        self.assertIn('"banned"', SRC)
        self.assertIn("400", SRC)

    def test_coupon_code_immutable_and_unique(self):
        self.assertIn("cannot be changed", SRC)
        self.assertIn("already exists", SRC)


if __name__ == "__main__":
    unittest.main()
