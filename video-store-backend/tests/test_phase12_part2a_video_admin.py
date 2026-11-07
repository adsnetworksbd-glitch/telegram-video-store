"""
Phase 12 / Part 2A — backup source, dashboard sections, secrets never exposed.
Pure rules + AST contract (no FastAPI / Firestore needed).
"""
import ast
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import admin_config as C  # noqa: E402
from app.services import admin_ops as O  # noqa: E402

EP = BACKEND / "app" / "api" / "v1" / "endpoints"
CFG_SRC = (EP / "admin_config.py").read_text(encoding="utf-8")
OPS_SRC = (EP / "admin_ops.py").read_text(encoding="utf-8")
VID_SRC = (EP / "videos.py").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return ast.get_source_segment(src, n)
    raise AssertionError(name)


class BackupSource(unittest.TestCase):
    ok = {"title": "A", "quality": "HD", "source_type": "direct_mp4", "category_ids": ["c1"],
          "primary_category_id": "c1", "price_bdt": 50, "has_source": True}

    def test_fields_are_declared_and_write_only(self):
        self.assertTrue(C.VIDEO_FIELDS["backup_source_url"]["write_only"])
        self.assertEqual(C.VIDEO_FIELDS["backup_source_type"]["options"], C.VIDEO_FIELDS["source_type"]["options"])

    def test_backup_must_be_https_and_known_type(self):
        self.assertEqual(C.video_problems({**self.ok, "backup_source_url": "https://b.example/v.mp4"}), [])
        self.assertTrue(any("backup_source_url" in p for p in C.video_problems({**self.ok, "backup_source_url": "http://b"})))
        self.assertTrue(any("backup_source_type" in p for p in C.video_problems({**self.ok, "backup_source_type": "nope"})))

    def test_backup_not_required(self):
        self.assertEqual(C.video_problems(self.ok), [])

    def test_never_returned_and_never_audited(self):
        view = _fn(CFG_SRC, "_video_view")
        self.assertNotIn('d.get("backup_source_url_encrypted"),', view)          # only a bool is exposed
        self.assertIn("has_backup_source=bool(", view)
        self.assertIn('"backup_source_url_encrypted", "created_at"', CFG_SRC)     # create audit excludes it
        self.assertIn('"backup_source_url_encrypted", "updated_at"', CFG_SRC)     # update audit excludes it

    def test_user_source_endpoint_stays_backward_compatible(self):
        fn = _fn(VID_SRC, "get_video_source")
        self.assertIn("backup: bool = False", fn)
        self.assertIn("check_video_access", fn)
        self.assertLess(fn.index("check_video_access"), fn.index("backup_source_url_encrypted"))   # access first
        self.assertIn('data.get("source_url_encrypted"', fn)


class Dashboard(unittest.TestCase):
    def test_top_video_view_whitelist(self):
        v = O.video_stat_view({"title": "T", "source_url_encrypted": "x", "backup_source_url_encrypted": "y",
                               "purchase_count": 3, "view_count": "bad"})
        self.assertEqual(v["purchase_count"], 3)
        self.assertEqual(v["view_count"], 0)
        self.assertNotIn("source_url_encrypted", v)
        self.assertNotIn("backup_source_url_encrypted", v)

    def test_sections_are_permission_gated(self):
        fn = _fn(OPS_SRC, "admin_dashboard")
        for perm in ("Perm.VIDEOS_VIEW", "Perm.ORDERS_VIEW", "Perm.AUDIT_VIEW"):
            self.assertIn(f"ctx.can({perm})", fn)
        self.assertIn("O.audit_admin_view", fn)       # activity is redacted
        self.assertIn("O.order_admin_view", fn)       # orders are whitelisted


if __name__ == "__main__":
    unittest.main()
