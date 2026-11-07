# Phase 5 — Automated Test Report

**Environment:** Python 3.12.3, Node 22, `tsc` 6.0.3 (global). **Network বন্ধ** → `fastapi`, `pydantic`, `firebase-admin`, `pytest`, `node_modules` ইনস্টল করা যায়নি।

## চালানো হয়েছে — `python -m unittest tests.test_static_contract` → **14/14 PASS**
| Test | ধরন |
|---|---|
| test_frontend_calls_exist_in_backend | Static (AST + Regex) |
| test_static_routes_declared_before_param_routes | Static |
| test_admin_routes_all_require_admin_dependency | Static |
| test_webhooks_fail_closed | Static (Source) |
| test_access_tokens_and_admin_tokens_are_separated | Static |
| test_submit_blocks_resubmission | Static |
| test_rate_limit_registered_before_cors | Static |
| test_no_hardcoded_secrets_in_repo | Static (Regex) |
| test_jwt_refresh_wired | Static (Frontend) |
| test_expired_flag_in_types_and_badge | Static (Frontend) |
| test_order_status_types_cover_backend | Static |
| test_hmac_helper_fail_closed | Unit (বাস্তব Execution) |
| test_rate_limiter | Unit (বাস্তব Execution) |
| test_fernet_roundtrip_with_ephemeral_key | Unit (বাস্তব Execution) |

**Mutation Check:** আসল (আগের) `orders.py`/`ads.py` দিয়ে চালালে ৩টি Test FAIL করে (route-order, resubmit, webhook fail-open) → Test গুলো বাস্তবে বাগ ধরে।
**অন্যান্য:** `python -m py_compile` সব Backend ফাইলে OK; `tsc` Syntax-only (`--noResolve`) পরিবর্তিত ৪টি TS/TSX ফাইলে Error নেই।

## চালানো **হয়নি** (PASS নয়)
| আইটেম | কারণ |
|---|---|
| FastAPI Startup / `/health` | `fastapi` ইনস্টল নেই |
| HTTP-লেভেল Endpoint/Webhook/Rate-limit Test | একই |
| JWT RS256 Issue/Verify | `python-jose` নেই |
| Firestore-নির্ভর Flow (Order, Entitlement, Ads) | Firebase SDK/Credentials নেই; Mock Firestore লেখা হয়নি |
| `tsc` সম্পূর্ণ Type-check | `node_modules`/React types নেই |
| `vite build` | একই |
| Telegram Web / Browser UI (Expired Badge) | Browser নেই |
| Binance/Monetag Live বা Sandbox | Credentials ও Network নেই |
