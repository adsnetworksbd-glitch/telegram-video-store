"""
Phase 12 / Part 1D — dashboard, orders & transactions, users, support, audit log, categories, admin accounts.
Pure rules (app.services.admin_ops) + AST contract of endpoints/admin_ops.py. No FastAPI needed.
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
from app.services import admin_ops as O  # noqa: E402

EP = BACKEND / "app" / "api" / "v1" / "endpoints"
SRC = (EP / "admin_ops.py").read_text()
TREE = ast.parse(SRC)
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


class Dashboard(unittest.TestCase):
    def test_counts_and_revenue_only_from_completed(self):
        orders = [
            {"status": "completed", "final_bdt": 100, "created_at": NOW - timedelta(hours=1), "completed_at": NOW - timedelta(minutes=30)},
            {"status": "completed", "final_bdt": 50.5, "created_at": NOW - timedelta(days=3), "completed_at": NOW - timedelta(days=3)},
            {"status": "completed", "final_bdt": 25, "created_at": NOW - timedelta(days=20), "completed_at": NOW - timedelta(days=20)},
            {"status": "payment_submitted", "final_bdt": 999, "created_at": NOW - timedelta(hours=2)},
            {"status": "under_review", "final_bdt": 999, "created_at": NOW - timedelta(days=1)},
            {"status": "failed", "final_bdt": 999, "created_at": NOW - timedelta(days=2)},
            {"status": "weird", "created_at": NOW},
        ]
        s = O.summarize_orders(orders, NOW)
        self.assertEqual(s["revenue_bdt"], {"today": 100.0, "last_7_days": 150.5, "last_30_days": 175.5})
        self.assertEqual(s["by_status"]["completed"], 3)
        self.assertEqual(s["awaiting_review"], 2)
        self.assertEqual(s["orders_in_window"], 7)
        self.assertEqual(s["orders_today"], 3)       # 1h ago, 2h ago, "weird" at NOW

    def test_bad_amounts_never_crash_or_count(self):
        s = O.summarize_orders([{"status": "completed", "final_bdt": "100", "created_at": NOW},
                                {"status": "completed", "final_bdt": True, "created_at": NOW},
                                {"status": "completed", "final_bdt": None}], NOW)
        self.assertEqual(s["revenue_bdt"]["last_30_days"], 0.0)

    def test_naive_datetimes_tolerated(self):
        s = O.summarize_orders([{"status": "completed", "final_bdt": 10, "created_at": datetime(2026, 11, 5, 9, 0)}], NOW)
        self.assertEqual(s["revenue_bdt"]["today"], 10.0)

    def test_statuses_match_order_flow(self):
        src = (EP / "orders.py").read_text() + (BACKEND / "app" / "services" / "fulfillment.py").read_text()
        for st in O.ORDER_STATUSES:
            self.assertIn(f'"{st}"', src, st)


class Views(unittest.TestCase):
    def test_user_view_whitelist_and_ban_flag(self):
        u = {"username": "a", "is_banned": False, "account_status": "banned", "refresh_token": "x", "telegram_id": "1", "password": "p"}
        v = O.user_admin_view("1", u)
        self.assertTrue(v["is_banned"])
        self.assertNotIn("refresh_token", v)
        self.assertNotIn("password", v)

    def test_order_and_tx_views_whitelist(self):
        self.assertNotIn("secret", O.order_admin_view("o", {"status": "completed", "secret": 1}))
        self.assertEqual(O.transaction_admin_view("t", {"amount_bdt": 5, "x": 1})["amount_bdt"], 5)
        self.assertNotIn("x", O.transaction_admin_view("t", {"x": 1}))

    def test_user_search(self):
        u = {"username": "Rahim_X", "first_name": "Rahim"}
        for q in ("rahim", "@rahim_x", "123", ""):
            self.assertTrue(O.matches_user_query("123456", u, q), q)
        self.assertFalse(O.matches_user_query("123456", u, "karim"))


class Support(unittest.TestCase):
    def test_status_changes(self):
        done = O.ticket_status_changes("resolved", NOW, "bob")
        self.assertEqual(done["resolved_at"], NOW)
        self.assertIsNone(O.ticket_status_changes("open", NOW, "bob")["resolved_at"])
        with self.assertRaises(ValueError):
            O.ticket_status_changes("deleted", NOW, "bob")

    def test_ticket_statuses_match_public_flow(self):
        self.assertEqual(O.TICKET_STATUSES[0], "open")           # misc.create_ticket writes "open"
        self.assertIn('"status": "open"', (EP / "misc.py").read_text())

    def test_faq_problems(self):
        self.assertEqual(O.faq_problems({"question": "Q?", "answer": "A", "display_order": 1, "is_visible": True}), [])
        for patch in ({"question": ""}, {"answer": "x" * 3001}, {"display_order": -1}, {"display_order": True}, {"is_visible": "yes"}):
            self.assertTrue(O.faq_problems({"question": "Q?", "answer": "A", **patch}), patch)


class Audit(unittest.TestCase):
    def test_redaction(self):
        out = O.redact({"role": "admin", "password_hash": "h", "nested": {"api_key": "k", "Token_Version": 3, "ok": 1},
                        "list": [{"source_url_encrypted": "z", "n": 1}]})
        self.assertEqual(out["role"], "admin")
        self.assertEqual(out["password_hash"], "[redacted]")
        self.assertEqual(out["nested"], {"api_key": "[redacted]", "Token_Version": "[redacted]", "ok": 1})
        self.assertEqual(out["list"][0], {"source_url_encrypted": "[redacted]", "n": 1})

    def test_redaction_depth_limited(self):
        deep: dict = {}
        cur = deep
        for _ in range(20):
            cur["a"] = {}
            cur = cur["a"]
        self.assertIn("[truncated]", str(O.redact(deep)))

    def test_view_redacts_snapshots(self):
        v = O.audit_admin_view("l", {"action": "x", "snapshot_after": {"password": "p", "role": "r"}, "junk": 1})
        self.assertEqual(v["snapshot_after"], {"password": "[redacted]", "role": "r"})
        self.assertNotIn("junk", v)

    def test_filters(self):
        a = {"action": "user_banned", "performed_by": "bob", "target_type": "user", "target_id": "9", "created_at": NOW}
        self.assertTrue(O.audit_matches(a))
        self.assertTrue(O.audit_matches(a, action="user_banned", performed_by="bob", target_type="user", target_id="9"))
        self.assertFalse(O.audit_matches(a, action="other"))
        self.assertFalse(O.audit_matches(a, performed_by="x"))
        self.assertTrue(O.audit_matches(a, since=NOW - timedelta(days=1), until=NOW + timedelta(days=1)))
        self.assertFalse(O.audit_matches(a, since=NOW + timedelta(seconds=1)))
        self.assertFalse(O.audit_matches({**a, "created_at": None}, since=NOW - timedelta(days=1)))


class Categories(unittest.TestCase):
    ok = {"name": "Action", "slug": "action", "description": None, "thumbnail_url": "https://x/y.png",
          "display_order": 3, "is_visible": True}

    def test_valid(self):
        self.assertEqual(O.category_problems(self.ok), [])
        self.assertEqual(O.category_problems({"name": "A", "thumbnail_url": ""}), [])

    def test_problems(self):
        for patch, frag in (({"name": " "}, "name"), ({"slug": "Bad Slug"}, "slug"), ({"slug": "a--b"}, "slug"),
                            ({"thumbnail_url": "http://x"}, "https"), ({"display_order": 10_001}, "display_order"),
                            ({"is_visible": 1}, "is_visible"), ({"description": "x" * 501}, "description")):
            self.assertTrue(any(frag in p for p in O.category_problems({**self.ok, **patch})), patch)

    def test_fields_match_public_category(self):
        src = (BACKEND / "app" / "services" / "mappers.py").read_text()
        for k in ("name", "slug", "thumbnail_url", "description", "video_count", "display_order"):
            self.assertIn(f'"{k}"', src)
        self.assertIn('"is_visible"', (EP / "videos.py").read_text())


class AdminAccounts(unittest.TestCase):
    def chg(self, **kw):
        base = dict(actor="boss", target="bob", target_role="admin", target_active=True,
                    new_role=None, new_active=None, other_active_super_admins=1)
        return O.admin_change_problem(**{**base, **kw})

    def test_allowed(self):
        self.assertIsNone(self.chg(new_role="moderator"))
        self.assertIsNone(self.chg(new_active=False))
        self.assertIsNone(self.chg(actor="bob"))                              # no change at all
        self.assertIsNone(self.chg(target_role="super_admin", new_role="admin"))   # another super remains

    def test_cannot_change_self(self):
        self.assertIn("own", self.chg(actor="bob", new_role="moderator"))
        self.assertIn("own", self.chg(actor="bob", new_active=False))
        self.assertIsNone(self.chg(actor="bob", new_role="admin"))            # same role = no change

    def test_last_super_admin_is_protected(self):
        kw = dict(target_role="super_admin", other_active_super_admins=0)
        self.assertIn("super admin", self.chg(new_role="admin", **kw))
        self.assertIn("super admin", self.chg(new_active=False, **kw))
        self.assertIsNone(self.chg(new_role="super_admin", **kw))
        self.assertIsNone(self.chg(target_active=False, new_active=True, **kw))

    def test_unknown_role_rejected(self):
        self.assertIn("role", self.chg(new_role="owner"))

    def test_password_rules(self):
        self.assertIsNone(O.password_problem("correct-horse-9"))
        for bad in ("short", "x" * 73, " leading-space1", "aaaaaaaaaaaa", 123, None, "ü" * 40):
            self.assertIsNotNone(O.password_problem(bad), bad)

    def test_account_view_has_no_secrets(self):
        v = O.admin_account_view("bob", {"role": "admin", "is_active": True, "password_hash": "h", "token_version": 4,
                                         "failed_attempts": 2, "locked_until": datetime.now(timezone.utc) + timedelta(minutes=5)})
        for k in ("password_hash", "token_version", "failed_attempts", "locked_until"):
            self.assertNotIn(k, v)
        self.assertTrue(v["is_locked"])

    def test_username_rule_matches_login_service(self):
        src = (BACKEND / "app" / "services" / "admin_auth.py").read_text()
        self.assertIn(O.ADMIN_ACCOUNT_FIELDS["username"]["pattern"], src)


class Schema(unittest.TestCase):
    def test_modules_registered_with_existing_permissions(self):
        mods = C.schema_for(R.ALL_PERMISSIONS)["modules"]
        for key in O.MODULES_1D:
            self.assertIn(key, mods)
            self.assertTrue(mods[key]["can_view"] and mods[key]["can_manage"], key)
        self.assertEqual(C.schema_for(frozenset())["version"], "12.1d")

    def test_role_visibility(self):
        mod = C.schema_for(R.permissions_for(R.MODERATOR))["modules"]
        self.assertTrue(mod["dashboard"]["can_view"] and mod["orders"]["can_view"] and mod["users"]["can_view"])
        self.assertTrue(mod["support"]["can_manage"] and mod["categories"]["can_view"])
        self.assertFalse(mod["audit"]["can_view"] or mod["admins"]["can_view"] or mod["categories"]["can_manage"])
        adm = C.schema_for(R.permissions_for(R.ADMIN))["modules"]
        self.assertTrue(adm["audit"]["can_view"] and adm["categories"]["can_manage"])
        self.assertFalse(adm["admins"]["can_view"])

    def test_schema_does_not_expose_secret_fields(self):
        spec = C.schema_for(R.ALL_PERMISSIONS)["modules"]["admins"]["fields"]["password"]
        self.assertTrue(spec["write_only"])
        self.assertNotIn("password_hash", str(C.schema_for(R.ALL_PERMISSIONS)["modules"]["admins"]))


class RouteContract(unittest.TestCase):
    def routes(self):
        out = []
        for fn in ast.walk(TREE):
            if isinstance(fn, ast.AsyncFunctionDef):
                for dec in fn.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and getattr(dec.func.value, "id", "") == "router":
                        out.append((fn, dec))
        return out

    def test_every_route_guarded_and_every_write_audited(self):
        rs = self.routes()
        self.assertEqual(len(rs), 24)
        for fn, dec in rs:
            seg = ast.get_source_segment(SRC, dec)
            self.assertIn("require_permission(Perm.", seg, fn.name)
            if dec.func.attr in ("post", "put", "patch", "delete"):
                self.assertIn("audit_log(", ast.get_source_segment(SRC, fn), fn.name)

    def test_permission_per_area(self):
        want = {"/dashboard": "DASHBOARD_VIEW", "/orders": "ORDERS_VIEW", "/transactions": "ORDERS_VIEW",
                "/audit-logs": "AUDIT_VIEW", "/admins": "ADMINS_MANAGE", "/faqs": "SUPPORT_MANAGE",
                "/support/tickets": "SUPPORT_MANAGE"}
        for fn, dec in self.routes():
            path = dec.args[0].value
            seg = ast.get_source_segment(SRC, dec)
            for prefix, perm in want.items():
                if path.startswith(prefix):
                    self.assertIn(f"Perm.{perm}", seg, path)
            if path.startswith("/categories"):
                self.assertIn("VIDEOS_VIEW" if dec.func.attr == "get" else "VIDEOS_MANAGE", seg, path)
            if path.startswith("/users"):
                self.assertIn("USERS_VIEW", seg, path)

    def test_no_clash_with_other_admin_routes(self):
        used = {(d.func.attr, d.args[0].value) for _, d in self.routes()}
        self.assertEqual(len(used), len(self.routes()))
        for f in EP.glob("admin*.py"):
            if f.name == "admin_ops.py":
                continue
            for fn in ast.walk(ast.parse(f.read_text())):
                if isinstance(fn, ast.AsyncFunctionDef):
                    for dec in fn.decorator_list:
                        if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.func, ast.Attribute):
                            self.assertNotIn((dec.func.attr, dec.args[0].value), used, f.name)

    def test_registered_and_no_new_collection(self):
        r = (BACKEND / "app" / "api" / "v1" / "router.py").read_text()
        self.assertIn("include_router(admin_ops.router)", r)
        self.assertNotIn('collection("', SRC)
        fb = (BACKEND / "app" / "db" / "firebase.py").read_text()
        for n in {a.attr for a in ast.walk(TREE) if isinstance(a, ast.Attribute) and getattr(a.value, "id", "") == "Col"}:
            self.assertIn(f"    {n}", fb)

    def test_secrets_never_returned(self):
        self.assertNotIn("password_hash\":", SRC.replace('"password_hash": await', ""))   # only written, never read into a response
        self.assertIn("admin_account_view", SRC)
        self.assertIn("to_thread(hash_password", SRC)                                    # bcrypt off the event loop
        self.assertNotIn("password=body.password", SRC)                                  # never passed to audit_log

    def test_sessions_revoked_on_role_active_password_change(self):
        fns = {fn.name: ast.get_source_segment(SRC, fn) for fn, _ in self.routes()}
        self.assertIn("token_version", fns["admin_update_admin"])            # role / active change → sessions end
        self.assertIn("token_version", fns["admin_reset_admin_password"])    # password reset → sessions end
        self.assertIn("locked_until", fns["admin_reset_admin_password"])    # …and lockout cleared

    def test_dashboard_and_scans_are_bounded(self):
        self.assertIn("DASHBOARD_ORDER_CAP", SRC)
        self.assertIn(".limit(cap)", SRC)
        self.assertIn("AUDIT_SCAN_CAP", SRC)

    def test_indexes_for_server_side_filters(self):
        import json
        idx = json.loads((BACKEND / "firestore.indexes.json").read_text())["indexes"]
        have = {(i["collectionGroup"], tuple(f["fieldPath"] for f in i["fields"])) for i in idx}
        for need in (("orders", ("status", "created_at")), ("orders", ("user_id", "created_at")),
                     ("transactions", ("user_id", "created_at")), ("support_tickets", ("status", "created_at")),
                     ("support_tickets", ("user_id", "created_at"))):
            self.assertIn(need, have)


if __name__ == "__main__":
    unittest.main()
