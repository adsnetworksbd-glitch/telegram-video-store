"""Phase 12 / Part 2C — server-side maintenance guard (offline; no FastAPI/Firebase calls)."""
import ast
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

EP = BACKEND / "app" / "api" / "v1" / "endpoints"


class MaintenanceRule(unittest.TestCase):
    def setUp(self):
        try:
            from app.services import maintenance as M
        except ModuleNotFoundError as e:       # fastapi is only needed for HTTPException
            self.skipTest(f"dependency missing offline: {e}")
        self.M = M

    def test_only_strict_true_locks(self):
        for cfg, expected in ((None, False), ({}, False), ({"maintenance_mode": False}, False),
                              ({"maintenance_mode": "true"}, False), ({"maintenance_mode": 1}, False),
                              ({"maintenance_mode": True}, True)):
            self.assertEqual(self.M.maintenance_active(cfg), expected, cfg)


def _calls_guard(path: Path, func: str) -> bool:
    tree = ast.parse(path.read_text())
    for fn in ast.walk(tree):
        if isinstance(fn, ast.AsyncFunctionDef) and fn.name == func:
            return any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ensure_not_in_maintenance"
                       for n in ast.walk(fn))
    return False


class GuardWiring(unittest.TestCase):
    def test_purchase_paths_are_guarded(self):
        self.assertTrue(_calls_guard(EP / "orders.py", "create_order"))
        self.assertTrue(_calls_guard(EP / "orders.py", "retry_order"))
        self.assertTrue(_calls_guard(EP / "ads.py", "start_ad_session"))

    def test_admin_auth_and_callbacks_are_not_guarded(self):
        for f in ("admin.py", "admin_auth.py", "admin_manage.py", "admin_ops.py", "admin_config.py", "auth.py"):
            self.assertNotIn("ensure_not_in_maintenance", (EP / f).read_text(), f)
        for fn in ("verify_order_payment", "submit_payment", "monetag_webhook", "provider_webhook", "check_ad_session"):
            src = EP / ("ads.py" if "ad" in fn or "webhook" in fn else "orders.py")
            self.assertFalse(_calls_guard(src, fn), fn)


if __name__ == "__main__":
    unittest.main()
