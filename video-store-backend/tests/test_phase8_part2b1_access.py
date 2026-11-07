"""
Phase 8 Part 2 (B-1) — access-control checks.
Standard library only (no FastAPI / pydantic / Firestore), like the other static
tests. Nothing here starts a server, touches Firestore, pays or shows an ad.

  • access_rules (entitlement_state / evaluate_access) is REAL code, EXECUTED.
  • Endpoint wiring (auth on every access endpoint, no access granted from
    request data, source gated by the access check, no deletes) is checked
    STATICALLY (AST / text). That proves the code is wired that way, it does not
    prove runtime behaviour against Firestore.
"""
import ast
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "video-store-backend"
FRONTEND = ROOT / "video-store-frontend" / "src"
EP = BACKEND / "app" / "api" / "v1" / "endpoints"

sys.path.insert(0, str(BACKEND))
from app.services.access_rules import entitlement_state, evaluate_access  # noqa: E402

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def ent(source, *, lifetime=False, expires=None, status="active"):
    return {"access_source": source, "is_lifetime": lifetime, "expires_at": expires, "status": status}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def func_src(path: Path, name: str) -> str:
    text = read(path)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{name} not found in {path.name}")


# ─── 1-4  the four access sources ────────────────────────────────────────────
class FourAccessSources(unittest.TestCase):
    def test_free_video(self):
        r = evaluate_access([], NOW, is_free=True)
        self.assertTrue(r["granted"]); self.assertEqual(r["source"], "free")
        self.assertTrue(r["is_lifetime"]); self.assertIsNone(r["expires_at"])

    def test_ads_unlock_active_with_expiry(self):
        r = evaluate_access([ent("ads_unlock", expires=NOW + 5 * H)], NOW)
        self.assertTrue(r["granted"]); self.assertEqual(r["source"], "ads_unlock")
        self.assertFalse(r["is_lifetime"]); self.assertEqual(r["expires_at"], NOW + 5 * H)

    def test_ads_unlock_expired(self):
        r = evaluate_access([ent("ads_unlock", expires=NOW - H)], NOW)
        self.assertFalse(r["granted"]); self.assertTrue(r["expired"]); self.assertIsNone(r["source"])

    def test_individual_purchase_lifetime(self):
        r = evaluate_access([ent("individual_purchase", lifetime=True)], NOW)
        self.assertTrue(r["granted"]); self.assertEqual(r["source"], "individual_purchase")
        self.assertTrue(r["is_lifetime"]); self.assertIsNone(r["expires_at"])

    def test_individual_purchase_custom_duration(self):
        r = evaluate_access([ent("individual_purchase", expires=NOW + 72 * H)], NOW)
        self.assertTrue(r["granted"]); self.assertEqual(r["expires_at"], NOW + 72 * H)

    def test_package_purchase(self):
        r = evaluate_access([ent("package_purchase", lifetime=True)], NOW)
        self.assertEqual(r["source"], "package_purchase"); self.assertTrue(r["granted"])

    def test_no_entitlement_is_locked_not_expired(self):
        r = evaluate_access([], NOW)
        self.assertFalse(r["granted"]); self.assertFalse(r["expired"]); self.assertEqual(r["active_sources"], [])


# ─── Lifetime / expiry rules ─────────────────────────────────────────────────
class LifetimeAndExpiry(unittest.TestCase):
    def test_lifetime_never_expires_even_with_old_expires_at(self):
        # a lifetime record is valid whatever expires_at holds
        self.assertEqual(entitlement_state(ent("individual_purchase", lifetime=True, expires=NOW - 999 * H), NOW), "active")
        far = NOW + timedelta(days=365 * 200)
        self.assertEqual(evaluate_access([ent("individual_purchase", lifetime=True)], far)["granted"], True)

    def test_expiry_boundary_is_exclusive(self):
        self.assertEqual(entitlement_state(ent("ads_unlock", expires=NOW), NOW), "expired")
        self.assertEqual(entitlement_state(ent("ads_unlock", expires=NOW + timedelta(seconds=1)), NOW), "active")

    def test_temporary_without_expiry_fails_closed(self):
        # previously check_video_access treated this as VALID forever
        self.assertEqual(entitlement_state(ent("ads_unlock", expires=None), NOW), "expired")
        self.assertFalse(evaluate_access([ent("ads_unlock", expires=None)], NOW)["granted"])

    def test_missing_is_lifetime_is_not_lifetime(self):
        d = {"access_source": "ads_unlock", "expires_at": None, "status": "active"}
        self.assertFalse(evaluate_access([d], NOW)["granted"])

    def test_garbage_expiry_values_fail_closed(self):
        for bad in ("2099-01-01", 4102444800, [], {}):
            self.assertFalse(evaluate_access([ent("ads_unlock", expires=bad)], NOW)["granted"], bad)

    def test_truthy_non_bool_lifetime_does_not_grant(self):
        for bad in ("false", "yes", 1, "true"):
            d = {"access_source": "ads_unlock", "is_lifetime": bad, "expires_at": None, "status": "active"}
            self.assertFalse(evaluate_access([d], NOW)["granted"], bad)

    def test_naive_datetime_treated_as_utc(self):
        naive_future = (NOW + H).replace(tzinfo=None)
        naive_past = (NOW - H).replace(tzinfo=None)
        self.assertTrue(evaluate_access([ent("ads_unlock", expires=naive_future)], NOW)["granted"])
        self.assertFalse(evaluate_access([ent("ads_unlock", expires=naive_past)], NOW)["granted"])

    def test_revoked_or_unknown_status_never_grants(self):
        for st in ("revoked", "expired", "cancelled", "", None):
            self.assertFalse(evaluate_access([ent("individual_purchase", lifetime=True, status=st)], NOW)["granted"], st)

    def test_revoked_is_not_reported_as_expired(self):
        r = evaluate_access([ent("individual_purchase", lifetime=True, status="revoked")], NOW)
        self.assertFalse(r["expired"])

    def test_expiry_is_judged_at_the_time_of_the_check(self):
        e = [ent("ads_unlock", expires=NOW + 2 * H)]
        self.assertTrue(evaluate_access(e, NOW + H)["granted"])
        late = evaluate_access(e, NOW + 3 * H)
        self.assertFalse(late["granted"]); self.assertTrue(late["expired"])


# ─── Multiple independent sources ────────────────────────────────────────────
class MultipleSourcesAreIndependent(unittest.TestCase):
    def test_expired_package_does_not_cancel_lifetime_purchase(self):
        r = evaluate_access([
            ent("package_purchase", expires=NOW - H),
            ent("individual_purchase", lifetime=True),
        ], NOW)
        self.assertTrue(r["granted"]); self.assertEqual(r["source"], "individual_purchase")
        self.assertTrue(r["is_lifetime"]); self.assertFalse(r["expired"])

    def test_expired_lifetime_neighbour_irrelevant_valid_ads_still_works(self):
        r = evaluate_access([ent("package_purchase", expires=NOW - 5 * H), ent("ads_unlock", expires=NOW + H)], NOW)
        self.assertTrue(r["granted"]); self.assertEqual(r["source"], "ads_unlock")

    def test_order_of_records_does_not_matter(self):
        a = [ent("ads_unlock", expires=NOW + H), ent("individual_purchase", lifetime=True), ent("package_purchase", expires=NOW - H)]
        results = []
        import itertools
        for perm in itertools.permutations(a):
            r = evaluate_access(list(perm), NOW)
            results.append((r["granted"], r["source"], r["is_lifetime"], tuple(r["active_sources"]), r["expired"]))
        self.assertEqual(len(set(results)), 1)

    def test_lifetime_beats_temporary(self):
        r = evaluate_access([ent("ads_unlock", expires=NOW + 9999 * H), ent("package_purchase", lifetime=True)], NOW)
        self.assertEqual(r["source"], "package_purchase"); self.assertTrue(r["is_lifetime"])

    def test_latest_expiry_wins_among_temporary(self):
        r = evaluate_access([ent("ads_unlock", expires=NOW + H), ent("individual_purchase", expires=NOW + 10 * H)], NOW)
        self.assertEqual(r["source"], "individual_purchase"); self.assertEqual(r["expires_at"], NOW + 10 * H)

    def test_paid_preferred_over_ads_when_otherwise_equal(self):
        r = evaluate_access([ent("ads_unlock", lifetime=True), ent("individual_purchase", lifetime=True)], NOW)
        self.assertEqual(r["source"], "individual_purchase")

    def test_all_valid_sources_are_listed_each_once_best_first(self):
        r = evaluate_access([
            ent("ads_unlock", expires=NOW + H),
            ent("ads_unlock", expires=NOW + 2 * H),            # a second, separate ads record
            ent("individual_purchase", lifetime=True),
            ent("package_purchase", expires=NOW - H),          # expired → not listed
        ], NOW)
        self.assertEqual(r["active_sources"], ["individual_purchase", "ads_unlock"])

    def test_expired_flag_only_when_nothing_valid(self):
        r = evaluate_access([ent("package_purchase", expires=NOW - H), ent("ads_unlock", expires=NOW - 2 * H)], NOW)
        self.assertFalse(r["granted"]); self.assertTrue(r["expired"])

    def test_one_malformed_record_does_not_break_the_others(self):
        r = evaluate_access([{"garbage": True}, ent("individual_purchase", lifetime=True)], NOW)
        self.assertTrue(r["granted"]); self.assertEqual(r["source"], "individual_purchase")

    def test_inputs_are_not_modified(self):
        recs = [ent("ads_unlock", expires=NOW + H), ent("individual_purchase", lifetime=True)]
        before = [dict(x) for x in recs]
        evaluate_access(recs, NOW)
        self.assertEqual(recs, before)

    def test_free_flag_wins_without_touching_entitlements(self):
        r = evaluate_access([ent("ads_unlock", expires=NOW - H)], NOW, is_free=True)
        self.assertEqual(r["source"], "free")


# ─── Backend is the authority (static wiring) ────────────────────────────────
ACCESS_ENDPOINTS = [
    (EP / "videos.py", "get_video"),
    (EP / "videos.py", "get_video_source"),
    (EP / "packages.py", "get_package"),
    (EP / "orders.py", "list_entitlements"),
    (EP / "orders.py", "check_video_entitlement"),
    (EP / "orders.py", "check_package_entitlement"),
    (EP / "orders.py", "create_order"),
    (EP / "ads.py", "start_ad_session"),
    (EP / "ads.py", "check_ad_session"),
]


class BackendIsTheAuthority(unittest.TestCase):
    def test_every_access_endpoint_takes_user_from_verified_auth(self):
        for path, name in ACCESS_ENDPOINTS:
            src = func_src(path, name)
            self.assertIn("Depends(get_current_user)", src, f"{name}: user must come from the verified JWT")

    def test_no_access_endpoint_accepts_a_user_id_from_the_client(self):
        for path, name in ACCESS_ENDPOINTS:
            text = read(path)
            node = next(n for n in ast.walk(ast.parse(text))
                        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)
            params = [a.arg for a in node.args.args + node.args.kwonlyargs]
            # the only `user_id` parameter is the dependency-injected one
            self.assertEqual(params.count("user_id"), 1, name)
            dflt = {a.arg: ast.get_source_segment(text, d) for a, d in zip(reversed(node.args.args), reversed(node.args.defaults))}
            self.assertEqual(dflt.get("user_id"), "Depends(get_current_user)", name)

    def test_request_bodies_carry_no_access_or_duration_fields(self):
        schema = read(BACKEND / "app" / "schemas" / "__init__.py")
        for cls in ("OrderCreateRequest", "AdSessionStartRequest", "AdSessionCompleteRequest"):
            m = re.search(rf"class {cls}\(BaseModel\):(.*?)\n\n\n", schema, re.S)
            self.assertIsNotNone(m, cls)
            for forbidden in ("expires_at", "is_lifetime", "duration", "access_source", "granted", "status", "user_id"):
                self.assertNotIn(forbidden, m.group(1), f"{cls} must not accept {forbidden}")

    def test_source_endpoint_checks_access_before_decrypting(self):
        src = func_src(EP / "videos.py", "get_video_source")
        self.assertLess(src.index("check_video_access("), src.index("decrypt_url("))
        # the 403 must be raised by the access result itself, before decrypting
        self.assertRegex(src, r"if not access\.granted:\s+raise HTTPException\(status_code=403")
        self.assertLess(src.index("if not access.granted"), src.index("decrypt_url("))
        self.assertIn('"no-store"', src)

    def test_source_endpoint_is_the_only_place_the_link_is_decrypted(self):
        for p in (BACKEND / "app").rglob("*.py"):
            if p.name in ("security.py",):
                continue
            if "decrypt_url(" in read(p):
                self.assertEqual(p.relative_to(BACKEND).as_posix(), "app/api/v1/endpoints/videos.py")

    def test_catalog_schemas_expose_no_source_url(self):
        schema = read(BACKEND / "app" / "schemas" / "__init__.py")
        for cls in ("Video", "VideoDetail", "Package", "PackageDetail", "AccessStatus", "Entitlement"):
            m = re.search(rf"class {cls}\([A-Za-z]+\):(.*?)\n\n\n", schema, re.S)
            self.assertIsNotNone(m, cls)
            self.assertNotIn("redirect_url", m.group(1), cls)
            self.assertNotIn("source_url", m.group(1), cls)

    def test_all_access_decisions_use_the_shared_rules(self):
        ent_src = read(BACKEND / "app" / "services" / "entitlement.py")
        self.assertEqual(ent_src.count("evaluate_access("), 3)  # free, video, package
        self.assertNotIn("had_expired", ent_src)  # the old inline logic is gone
        self.assertIn("entitlement_state(", func_src(EP / "orders.py", "list_entitlements"))

    def test_rules_output_matches_the_AccessStatus_schema_fields(self):
        # AccessStatus(**evaluate_access(...)) is built in entitlement.py; pydantic is
        # not installed here, so compare the key sets via the AST instead.
        text = read(BACKEND / "app" / "schemas" / "__init__.py")
        cls = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == "AccessStatus")
        fields = {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)}
        for is_free, ents in ((True, []), (False, []), (False, [ent("ads_unlock", expires=NOW + H)])):
            self.assertEqual(set(evaluate_access(ents, NOW, is_free=is_free)), fields)

    def test_free_requires_published(self):
        src = func_src(BACKEND / "app" / "services" / "entitlement.py", "check_video_access")
        self.assertRegex(src, r'is_free"\)\s+and\s+v\.get\("is_published"\)')

    def test_paid_and_ads_entitlements_are_separate_records(self):
        # ads webhook creates its own entitlement; fulfilment creates its own, per order
        self.assertIn('access_source="ads_unlock"', read(EP / "ads.py"))
        ful = read(BACKEND / "app" / "services" / "fulfillment.py")
        self.assertIn('"individual_purchase" if content_type == "video" else "package_purchase"', ful)
        self.assertIn('entitlement_id=f"ent_{order_id}"', ful)

    def test_existing_access_blocks_repurchase_and_second_ad_session(self):
        self.assertIn("has_any_access(", func_src(EP / "orders.py", "create_order"))
        self.assertIn("status_code=409", func_src(EP / "orders.py", "create_order"))
        self.assertIn("has_any_access(", func_src(EP / "ads.py", "start_ad_session"))

    def test_frontend_cannot_grant_access_via_ad_callbacks(self):
        ads = read(EP / "ads.py")
        # the only create_entitlement call lives in the signed S2S webhook
        self.assertEqual(ads.count("create_entitlement("), 1)
        # signature check moved into the provider module in Phase 9; the endpoint
        # must delegate to it before doing anything else
        self.assertIn("_handle_provider_callback", func_src(EP / "ads.py", "monetag_webhook"))
        self.assertIn("verify_callback(", func_src(EP / "ads.py", "_handle_provider_callback"))
        self.assertIn("verify_hmac_sha256_hex", read(BACKEND / "app/services/ad_providers/monetag.py"))
        self.assertNotIn("create_entitlement(", func_src(EP / "ads.py", "check_ad_session"))

    def test_history_is_never_deleted(self):
        for p in (BACKEND / "app").rglob("*.py"):
            text = read(p)
            for m in re.finditer(r"collection\(Col\.(ENTITLEMENTS|ORDERS|TRANSACTIONS|AD_SESSIONS)\)[^\n]*\.delete\(", text):
                self.fail(f"{p.name}: deletes {m.group(1)}")
        for p in (BACKEND / "app").rglob("*.py"):
            self.assertNotRegex(read(p), r"ENTITLEMENTS\)\.document\([^)]*\)\.delete", p.name)

    def test_get_current_user_rejects_missing_invalid_unknown_and_banned(self):
        src = func_src(BACKEND / "app" / "core" / "deps.py", "get_current_user")
        self.assertIn("credentials is None", src)
        self.assertIn("decode_access_token", src)
        self.assertIn("HTTP_401_UNAUTHORIZED", src)
        self.assertIn("is_blocked(", src)
        self.assertIn("HTTP_403_FORBIDDEN", src)
        # it must verify the signature/expiry BEFORE touching the database
        self.assertLess(src.index("decode_access_token"), src.index("get_db()"))


# ─── Frontend contracts (static) ─────────────────────────────────────────────
class FrontendDisplaysBackendDecision(unittest.TestCase):
    def test_display_logic_is_pure_and_has_no_grant_path(self):
        src = read(FRONTEND / "components" / "access" / "accessDisplay.ts")
        for banned in ("fetch(", "axios", "localStorage", "sessionStorage", "Date.now("):
            self.assertNotIn(banned, src)

    def test_all_seven_states_exist(self):
        meta = read(FRONTEND / "components" / "access" / "AccessState.tsx")
        for title in ("Locked", "Free", "Ads Unlock Available", "Purchase Available",
                      "Already Unlocked", "Active Access", "Expired Access"):
            self.assertIn(f"title: '{title}'", meta)

    def test_detail_pages_pass_status_and_revalidate(self):
        for page in ("VideoDetail", "PackageDetail"):
            src = read(FRONTEND / "pages" / page / "index.tsx")
            self.assertIn("useAccessRevalidation(", src)
            self.assertIn("accessApi.check", src)
        self.assertIn("onAccessInvalid={refreshAccess}", read(FRONTEND / "pages" / "VideoDetail" / "index.tsx"))

    def test_open_goes_only_through_the_backend_source_endpoint(self):
        btn = read(FRONTEND / "components" / "access" / "index.tsx")
        self.assertIn("useOpenSource(", btn)
        self.assertNotIn("handleSourceRedirect", btn)
        hook = read(FRONTEND / "hooks" / "useOpenSource.ts")
        self.assertIn("accessApi.getSource(", hook)
        self.assertIn("status === 403", hook)

    def test_no_dead_repurchase_button_while_access_is_valid(self):
        btn = read(FRONTEND / "components" / "access" / "index.tsx")
        self.assertNotIn("Option to also purchase lifetime", btn)

    def test_access_calls_are_response_guarded(self):
        api = read(FRONTEND / "api" / "index.ts")
        block = api[api.index("export const accessApi"):api.index("export const entitlementsApi")]
        self.assertEqual(block.count(".then(ok("), 3)

    def test_my_purchases_has_no_delete_and_refreshes_on_denial(self):
        src = read(FRONTEND / "pages" / "MyPurchases" / "index.tsx")
        self.assertIsNone(re.search(r"\.delete\(|onDelete|onRemove|handleDelete|handleRemove|deleteEntitlement", src))
        self.assertIn("useOpenSource(list.reload)", src)

    def test_type_matches_schema_field(self):
        self.assertIn("active_sources", read(BACKEND / "app" / "schemas" / "__init__.py"))
        self.assertIn("active_sources", read(FRONTEND / "types" / "index.ts"))


if __name__ == "__main__":
    unittest.main()
