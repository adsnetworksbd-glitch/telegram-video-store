"""
Phase 8 Part 2A — frontend/backend API-connection checks.
Standard library only (no FastAPI / pydantic / Firebase needed), like the other
static tests: they never start the server and never touch Firestore.

  • normalize_source_type is REAL code, executed.
  • Everything else is a static (AST / text) contract check of the source files.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "video-store-backend"
FRONTEND = ROOT / "video-store-frontend" / "src"
EP = BACKEND / "app" / "api" / "v1" / "endpoints"

sys.path.insert(0, str(BACKEND))
from app.services.source_types import normalize_source_type, SUPPORTED_SOURCE_TYPES  # noqa: E402


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def func_src(path: Path, name: str) -> str:
    text = read(path)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{name} not found in {path.name}")


class SourceTypeNormalisation(unittest.TestCase):
    def test_supported_types_pass_through(self):
        for t in SUPPORTED_SOURCE_TYPES:
            self.assertEqual(normalize_source_type(t), t)

    def test_matches_the_schema_literal_and_frontend_type(self):
        schema = read(BACKEND / "app" / "schemas" / "__init__.py")
        block = re.search(r"SourceType = Literal\[(.*?)\]", schema, re.S).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)"', block)), set(SUPPORTED_SOURCE_TYPES))
        ts = read(FRONTEND / "types" / "index.ts")
        tsblock = re.search(r"export type SourceType =(.*?)\n\n", ts, re.S).group(1)
        self.assertEqual(set(re.findall(r"'(\w+)'", tsblock)), set(SUPPORTED_SOURCE_TYPES))

    def test_unknown_or_bad_values_fall_back_to_custom_url(self):
        for bad in ("youtube", "", None, 7, [], "GOOGLE_DRIVE", " dropbox"):
            self.assertEqual(normalize_source_type(bad), "custom_url")


class ListEndpointsSkipMalformedDocuments(unittest.TestCase):
    """One bad Firestore document must not turn a whole list into a 500."""

    def test_no_list_endpoint_builds_videos_directly(self):
        for name in ("list_videos", "featured_videos", "trending_videos", "latest_videos",
                     "get_category", "category_videos"):
            src = func_src(EP / "videos.py", name)
            self.assertNotIn("_doc_to_video(", src, name)
            self.assertIn("_videos_from_docs(", src, name)

    def test_package_endpoints_use_safe_builders(self):
        for name in ("list_packages", "featured_packages"):
            self.assertIn("_packages_from_docs(", func_src(EP / "packages.py", name))
            self.assertNotIn("_doc_to_package(", func_src(EP / "packages.py", name))
        self.assertIn("_safe_package(", func_src(EP / "packages.py", "get_package"))
        self.assertIn("_safe_video(", func_src(EP / "packages.py", "get_package"))

    def test_search_uses_safe_builders(self):
        src = func_src(EP / "misc.py", "search")
        self.assertIn("_safe_video(", src); self.assertIn("_safe_package(", src)
        self.assertNotIn("_doc_to_video(", src); self.assertNotIn("_doc_to_package(", src)

    def test_safe_builders_only_swallow_validation_errors_and_log(self):
        for path, name in ((EP / "videos.py", "_safe_video"), (EP / "packages.py", "_safe_package")):
            src = func_src(path, name)
            self.assertIn("except ValidationError", src, name)
            self.assertNotIn("except Exception", src, name)      # real bugs must still surface
            self.assertIn("logger.warning", src, name)

    def test_detail_endpoints_answer_404_not_500_for_malformed_docs(self):
        self.assertRegex(func_src(EP / "videos.py", "get_video"), r"is None:\s+raise HTTPException\(status_code=404")
        self.assertRegex(func_src(EP / "packages.py", "get_package"), r"is None:\s+raise HTTPException\(status_code=404")


class SourceHandling(unittest.TestCase):
    def test_source_endpoint_is_never_cached(self):
        src = func_src(EP / "videos.py", "get_video_source")
        self.assertIn('"Cache-Control"] = "no-store"', src)

    def test_source_endpoint_still_checks_access_before_decrypting(self):
        src = func_src(EP / "videos.py", "get_video_source")
        self.assertLess(src.index("check_video_access"), src.index("decrypt_url"))
        self.assertIn("status_code=403", src)
        self.assertIn("Depends(get_current_user)", src)

    def test_source_types_are_normalised_in_detail_and_source(self):
        self.assertIn("normalize_source_type(", func_src(EP / "videos.py", "get_video"))
        self.assertIn("normalize_source_type(", func_src(EP / "videos.py", "get_video_source"))

    def test_no_catalog_response_model_carries_a_source_link(self):
        tree = ast.parse(read(BACKEND / "app" / "schemas" / "__init__.py"))
        banned = re.compile(r"source_url|redirect_url|download_url|video_url|file_url|telegram_file_id")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in {
                "Video", "VideoDetail", "VideoListResponse", "Package", "PackageDetail",
                "PackageListResponse", "Category", "Entitlement", "SearchResponse",
            }:
                fields = [n.target.id for n in node.body if isinstance(n, ast.AnnAssign)]
                self.assertEqual([f for f in fields if banned.search(f)], [], node.name)

    def test_only_the_source_endpoint_returns_a_redirect_url(self):
        offenders = []
        for f in EP.glob("*.py"):
            for node in ast.walk(ast.parse(read(f))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "SourceAccess":
                    offenders.append((f.name, node.lineno))
        self.assertEqual([o[0] for o in offenders], ["videos.py"])


class FrontendApiLayer(unittest.TestCase):
    def test_single_http_client(self):
        hits = [str(p.relative_to(FRONTEND)) for p in FRONTEND.rglob("*.ts*")
                if re.search(r"axios\.create\(|\bfetch\(", read(p))]
        self.assertEqual(hits, ["api/client.ts"])

    def test_pages_do_not_import_axios_directly(self):
        for p in list((FRONTEND / "pages").rglob("*.tsx")) + list((FRONTEND / "components").rglob("*.tsx")):
            self.assertNotRegex(read(p), r"from 'axios'", p.name)

    def test_catalog_service_calls_are_response_guarded(self):
        src = read(FRONTEND / "api" / "index.ts")
        for call in ("'/videos'", "'/videos/featured'", "'/videos/trending'", "'/videos/latest'",
                     "'/categories'", "'/packages'", "'/packages/featured'", "'/entitlements'",
                     "'/orders/history'", "'/search'", "'/user/transactions'", "'/user/notifications'",
                     "'/support/faq'", "'/config'", "'/config/homepage'", "'/user/profile'"):
            m = re.search(r"api\.(?:get|post)<[^\n]*?>\(\s*" + re.escape(call) + r"[^\n]*", src)
            self.assertIsNotNone(m, call)
            # one service method = text up to the next blank line
            end = src.find("\n\n", m.start())
            window = src[m.start(): end if end != -1 else len(src)]
            self.assertIn(".then(ok(", window, f"{call} is not response-guarded")

    def test_login_response_is_guarded_so_no_tokenless_authentication(self):
        src = read(FRONTEND / "api" / "index.ts")
        login = src[src.index("login:"): src.index("refresh:")]
        self.assertIn("access_token", login); self.assertIn(".then(ok(", login)

    def test_non_json_success_is_rejected_in_the_interceptor(self):
        src = read(FRONTEND / "api" / "client.ts")
        self.assertRegex(src, r"typeof res\.data === 'string'")
        self.assertIn("invalidResponseError", src)

    def test_refresh_failure_distinguishes_connection_loss_from_a_rejected_session(self):
        src = read(FRONTEND / "api" / "client.ts")
        self.assertIn("transient", src)
        self.assertRegex(src, r"status === undefined \|\| status >= 500")

    def test_only_get_is_auto_retried(self):
        src = read(FRONTEND / "api" / "client.ts")
        self.assertRegex(src, r"\(original\.method \?\? 'get'\)\.toLowerCase\(\) === 'get' && isTransient")

    def test_token_is_never_persisted(self):
        for p in FRONTEND.rglob("*.ts*"):
            text = read(p)
            if re.search(r"(localStorage|sessionStorage)\.setItem\([^)]*(token|jwt)", text, re.I):
                self.fail(f"token persisted in {p}")

    def test_app_shell_keeps_settings_current(self):
        src = read(FRONTEND / "components" / "layout" / "index.tsx")
        self.assertIn("refreshAppConfig", src)
        self.assertIn("maintenance_mode", src)


class NoHardcodedBusinessData(unittest.TestCase):
    """Prices / titles / sections must come from the Backend, never from page code."""

    def test_no_mock_data_files_or_arrays(self):
        for p in FRONTEND.rglob("*.ts*"):
            name = p.name.lower()
            self.assertNotIn("mock", name); self.assertNotIn("fixture", name)
            self.assertNotRegex(read(p), r"\b(MOCK_|mockVideos|mockPackages|dummyVideos|SAMPLE_VIDEOS)", p.name)

    def test_pages_have_no_literal_prices(self):
        for p in (FRONTEND / "pages").rglob("*.tsx"):
            text = re.sub(r"//.*", "", read(p))
            self.assertNotRegex(text, r"(?:৳|\bBDT\b|\bUSDT\b)\s?\d{2,}", p.name)

    def test_every_list_page_loads_through_the_api_layer(self):
        expect = {
            "Home": "videosApi", "Categories": "categoriesApi", "CategoryDetail": "categoriesApi",
            "AllVideos": "videosApi", "VideoDetail": "videosApi", "Packages": "packagesApi",
            "PackageDetail": "packagesApi", "MyPurchases": "entitlementsApi", "Account": "userApi",
            "Transactions": "userApi", "Notifications": "userApi", "Search": "searchApi",
            "Support": "supportApi",
        }
        for page, api in expect.items():
            text = read(FRONTEND / "pages" / page / "index.tsx")
            self.assertRegex(text, r"from '@/api'", page)
            self.assertIn(api, text, page)


class PageStates(unittest.TestCase):
    """Loading / empty / error / retry exist on every connected page."""

    def pages(self):
        return ["Home", "Categories", "CategoryDetail", "AllVideos", "VideoDetail", "Packages",
                "PackageDetail", "MyPurchases", "Transactions", "Notifications", "Search", "Support"]

    def test_error_state_has_retry_everywhere(self):
        for pg in self.pages():
            text = read(FRONTEND / "pages" / pg / "index.tsx")
            self.assertRegex(text, r"onRetry=", pg)

    def test_loading_uses_skeletons_on_data_lists(self):
        for pg in ("Home", "Categories", "AllVideos", "Packages", "VideoDetail", "PackageDetail",
                   "MyPurchases", "Transactions", "Notifications", "CategoryDetail"):
            text = read(FRONTEND / "pages" / pg / "index.tsx")
            self.assertRegex(text, r"Skeleton|isLoading=\{loading\}|VideoGrid|PackageCardSkeleton|CategoryCardSkeleton", pg)

    def test_detail_pages_treat_404_as_not_found_without_retry(self):
        for pg in ("VideoDetail", "PackageDetail"):
            text = read(FRONTEND / "pages" / pg / "index.tsx")
            self.assertIn("getErrorStatus(e) === 404", text, pg)

    def test_paginated_hook_always_clears_loading(self):
        text = read(FRONTEND / "hooks" / "usePaginatedList.ts")
        self.assertRegex(text, r"finally \{[^}]*setLoading\(false\)", )
        self.assertIn("errorMessage", text)

    def test_connection_message_is_shown_instead_of_generic_text(self):
        for pg in ("AllVideos", "Packages", "Categories", "Search", "Home", "VideoDetail", "PackageDetail"):
            text = read(FRONTEND / "pages" / pg / "index.tsx")
            self.assertRegex(text, r"errorMessage|connectionMessage", pg)


if __name__ == "__main__":
    unittest.main()
