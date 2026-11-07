"""
Phase 12 / Part 1A — admin login, roles, permissions.

  A. Roles & permissions  — pure logic (always runs).
  B. Route guards         — AST/source inspection of the real endpoint files (always runs).
  C. Auth service         — the real app.services.admin_auth against an in-memory FAKE
                            Firestore (MOCK persistence). Real bcrypt/JWT libraries are
                            required; skipped (not passed) when they are not installed.
"""
import ast
import asyncio
import importlib.util
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
EP = BACKEND / "app" / "api" / "v1" / "endpoints"
sys.path.insert(0, str(BACKEND))

from app.core import admin_roles as R  # noqa: E402


# ═══ A. Roles & permissions ═══════════════════════════════════════════════════
class RolePermissions(unittest.TestCase):
    def test_three_roles(self):
        self.assertEqual(set(R.ROLES), {"super_admin", "admin", "moderator"})

    def test_super_admin_has_everything(self):
        self.assertEqual(R.permissions_for(R.SUPER_ADMIN), R.ALL_PERMISSIONS)

    def test_admin_lacks_only_super_only_permissions(self):
        lacking = R.ALL_PERMISSIONS - R.permissions_for(R.ADMIN)
        self.assertEqual(lacking, {R.Perm.ADS_MANAGE, R.Perm.PAYMENT_METHODS_MANAGE,
                                   R.Perm.SETTINGS_MANAGE, R.Perm.ADMINS_MANAGE})

    def test_moderator_is_view_and_support_only(self):
        mod = R.permissions_for(R.MODERATOR)
        for p in (R.Perm.PAYMENTS_REVIEW, R.Perm.USERS_MANAGE, R.Perm.VIDEOS_MANAGE,
                  R.Perm.ADMINS_MANAGE, R.Perm.PAYMENT_METHODS_MANAGE, R.Perm.ADS_MANAGE):
            self.assertNotIn(p, mod)
        self.assertIn(R.Perm.DASHBOARD_VIEW, mod)
        self.assertIn(R.Perm.SUPPORT_MANAGE, mod)

    def test_roles_are_strictly_nested(self):
        self.assertLess(R.permissions_for(R.MODERATOR), R.permissions_for(R.ADMIN))
        self.assertLess(R.permissions_for(R.ADMIN), R.permissions_for(R.SUPER_ADMIN))

    def test_unknown_or_missing_role_fails_closed(self):
        for bad in (None, "", "root", "ADMIN", "super-admin"):
            self.assertEqual(R.permissions_for(bad), frozenset())
            self.assertFalse(R.AdminContext("x", bad, "x", "firestore").can(R.Perm.DASHBOARD_VIEW))

    def test_public_view_has_no_secrets(self):
        d = R.AdminContext("rahim", "admin", "Rahim", "firestore").public()
        self.assertEqual(set(d), {"username", "display_name", "role", "permissions"})
        self.assertEqual(d["permissions"], sorted(d["permissions"]))


# ═══ B. Route guards (source inspection) ══════════════════════════════════════
class RouteGuards(unittest.TestCase):
    def _routes(self, fname):
        """[(function name, decorator source, args source)] for every @router.* route."""
        tree = ast.parse((EP / fname).read_text())
        out = []
        for n in tree.body:
            if isinstance(n, ast.AsyncFunctionDef):
                for d in n.decorator_list:
                    if isinstance(d, ast.Call) and ast.unparse(d.func).startswith("router."):
                        out.append((n.name, ast.unparse(d), ast.unparse(n.args)))
        return out

    def test_every_admin_route_has_a_permission_guard_and_admin_auth(self):
        for f in ("admin.py", "admin_payment_methods.py"):
            routes = self._routes(f)
            self.assertGreaterEqual(len(routes), 5)
            for name, deco, args in routes:
                self.assertIn("require_permission(Perm.", deco, f"{f}:{name} has no permission guard")
                self.assertIn("get_current_admin", args, f"{f}:{name} lacks admin auth")

    def test_permission_mapping_of_existing_routes(self):
        want = {"approve_payment": "PAYMENTS_REVIEW", "reject_payment": "PAYMENTS_REVIEW",
                "list_pending_payments": "PAYMENTS_REVIEW", "payment_detail": "PAYMENTS_REVIEW",
                "reverify_payment": "PAYMENTS_REVIEW", "list_ad_networks": "ADS_MANAGE",
                "upsert_ad_network": "ADS_MANAGE", "admin_expire_stale_orders": "PAYMENTS_REVIEW",
                "admin_list_payment_methods": "PAYMENT_METHODS_MANAGE"}
        got = {n: re.search(r"Perm\.(\w+)", d).group(1)
               for f in ("admin.py", "admin_payment_methods.py") for n, d, _ in self._routes(f)}
        for name, perm in want.items():
            self.assertEqual(got[name], perm, name)

    def test_login_is_the_only_unauthenticated_admin_route(self):
        names = [n for n, _, a in self._routes("admin_auth.py") if "get_admin_context" not in a]
        self.assertEqual(names, ["admin_login"])

    def test_router_includes_admin_auth(self):
        self.assertIn("api_router.include_router(admin_auth.router)",
                      (EP.parent / "router.py").read_text())

    def test_role_is_never_taken_from_the_token(self):
        svc = (BACKEND / "app" / "services" / "admin_auth.py").read_text()
        self.assertNotIn('claims.get("role")', svc)
        self.assertNotIn('claims["role"]', svc)


# ═══ C. Auth service with fake Firestore ══════════════════════════════════════
_HAVE_LIBS = all(importlib.util.find_spec(m) for m in ("jose", "passlib", "firebase_admin", "pydantic_settings"))


class _Snap:
    def __init__(self, d):
        self.exists, self._d = d is not None, d

    def to_dict(self):
        return None if self._d is None else dict(self._d)


class _Ref:
    def __init__(self, store, key):
        self.store, self.key = store, key

    async def get(self):
        return _Snap(self.store.get(self.key))

    async def update(self, upd):
        self.store[self.key].update(upd)


class _Col:
    def __init__(self, store):
        self.store = store

    def document(self, key):
        return _Ref(self.store, key)


class _DB:
    def __init__(self):
        self.admins = {}

    def collection(self, name):
        assert name == "admin_users", name
        return _Col(self.admins)


@unittest.skipUnless(_HAVE_LIBS, "python-jose / passlib / firebase-admin / pydantic-settings not installed")
class AuthService(unittest.TestCase):
    def setUp(self):
        from app.services import admin_auth
        from app.core.security import hash_password
        self.svc, self.hash = admin_auth, hash_password
        self.db = _DB()
        self.pw = "correct-horse-battery"
        self.db.admins["rahim"] = {
            "username": "rahim", "role": "admin", "display_name": "Rahim", "is_active": True,
            "password_hash": hash_password(self.pw), "token_version": 0,
            "failed_attempts": 0, "locked_until": None,
        }
        self._p = [
            mock.patch.object(admin_auth, "get_db", lambda: self.db),
            mock.patch.object(admin_auth.settings, "ADMIN_USERNAME", "root"),
            mock.patch.object(admin_auth.settings, "ADMIN_PASSWORD_HASH", hash_password("env-secret-pass")),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def run_(self, coro):
        return asyncio.run(coro)

    def test_firestore_admin_login_ok_and_username_is_case_insensitive(self):
        r = self.run_(self.svc.authenticate_admin("  Rahim ", self.pw))
        self.assertEqual((r.status, r.ctx.role, r.ctx.source), ("ok", "admin", "firestore"))
        self.assertIsNotNone(self.db.admins["rahim"]["last_login_at"])

    def test_wrong_password_and_unknown_user_are_both_invalid(self):
        self.assertEqual(self.run_(self.svc.authenticate_admin("rahim", "nope-nope-nope")).status, "invalid")
        self.assertEqual(self.run_(self.svc.authenticate_admin("ghost", self.pw)).status, "invalid")
        self.assertEqual(self.run_(self.svc.authenticate_admin("a/b", self.pw)).status, "invalid")

    def test_env_admin_is_super_admin(self):
        r = self.run_(self.svc.authenticate_admin("root", "env-secret-pass"))
        self.assertEqual((r.status, r.ctx.role, r.ctx.source), ("ok", "super_admin", "env"))
        self.assertEqual(self.run_(self.svc.authenticate_admin("root", "wrong-wrong-wrong")).status, "invalid")

    def test_env_admin_disabled_when_hash_missing(self):
        with mock.patch.object(self.svc.settings, "ADMIN_PASSWORD_HASH", ""):
            self.assertEqual(self.run_(self.svc.authenticate_admin("root", "")).status, "invalid")

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            self.assertEqual(self.run_(self.svc.authenticate_admin("rahim", "bad-bad-bad-bad")).status, "invalid")
        r = self.run_(self.svc.authenticate_admin("rahim", self.pw))     # even the right password
        self.assertEqual(r.status, "locked")
        self.assertGreater(r.retry_after, 0)
        self.db.admins["rahim"]["locked_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(self.run_(self.svc.authenticate_admin("rahim", self.pw)).status, "ok")

    def test_success_resets_failure_counter(self):
        self.run_(self.svc.authenticate_admin("rahim", "bad-bad-bad-bad"))
        self.run_(self.svc.authenticate_admin("rahim", self.pw))
        self.assertEqual(self.db.admins["rahim"]["failed_attempts"], 0)

    def test_disabled_account_cannot_log_in(self):
        self.db.admins["rahim"]["is_active"] = False
        self.assertEqual(self.run_(self.svc.authenticate_admin("rahim", self.pw)).status, "disabled")
        self.assertEqual(self.run_(self.svc.authenticate_admin("rahim", "bad-bad-bad-bad")).status, "invalid")

    def test_invalid_role_in_database_is_denied(self):
        self.db.admins["rahim"]["role"] = "owner"
        self.assertEqual(self.run_(self.svc.authenticate_admin("rahim", self.pw)).status, "disabled")
        self.assertIsNone(self.run_(self.svc.resolve_admin_session({"sub": "rahim", "tv": 0})))

    def test_session_uses_live_role_not_token(self):
        self.db.admins["rahim"]["role"] = "moderator"
        ctx = self.run_(self.svc.resolve_admin_session({"sub": "rahim", "tv": 0, "role": "admin"}))
        self.assertEqual(ctx.role, "moderator")

    def test_session_revoked_by_token_version_disable_or_delete(self):
        claims = {"sub": "rahim", "tv": 0}
        self.assertIsNotNone(self.run_(self.svc.resolve_admin_session(claims)))
        self.db.admins["rahim"]["token_version"] = 1
        self.assertIsNone(self.run_(self.svc.resolve_admin_session(claims)))
        self.db.admins["rahim"]["token_version"] = 0
        self.db.admins["rahim"]["is_active"] = False
        self.assertIsNone(self.run_(self.svc.resolve_admin_session(claims)))
        del self.db.admins["rahim"]
        self.assertIsNone(self.run_(self.svc.resolve_admin_session(claims)))

    def test_session_for_unknown_user_or_bad_claims(self):
        for claims in ({"sub": "ghost", "tv": 0}, {"sub": "", "tv": 0}, {"sub": "rahim", "tv": "x"}):
            self.assertIsNone(self.run_(self.svc.resolve_admin_session(claims)))

    def test_env_admin_session_ok_only_with_tv_zero(self):
        self.assertEqual(self.run_(self.svc.resolve_admin_session({"sub": "root", "tv": 0})).role, "super_admin")
        self.assertIsNone(self.run_(self.svc.resolve_admin_session({"sub": "root", "tv": 3})))

    def test_firestore_record_overrides_env_admin_of_same_name(self):
        self.db.admins["root"] = {"username": "root", "role": "moderator", "is_active": False,
                                  "password_hash": self.hash("x" * 12), "token_version": 0}
        self.assertEqual(self.run_(self.svc.authenticate_admin("root", "env-secret-pass")).status, "invalid")
        self.assertIsNone(self.run_(self.svc.resolve_admin_session({"sub": "root", "tv": 0})))


if __name__ == "__main__":
    unittest.main()
