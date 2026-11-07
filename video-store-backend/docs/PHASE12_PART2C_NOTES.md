# Phase 12 — Part 2C / 3 (Final) notes

## Done
**Backend**
- `app/services/maintenance.py` (new): Maintenance Mode is now enforced on the server for everything that STARTS a purchase/unlock — `POST /orders`, `POST /orders/{id}/retry`, `POST /ads/session/start` return **503** with the admin's maintenance message. Reads, auth, already-submitted payment verification, ad-provider callbacks and all `/admin/*` APIs are intentionally NOT blocked (an admin must be able to switch it off; a payment already made must still resolve). Only a strict boolean `true` locks the store.
- `app_settings` field help text updated to say so. Test: `tests/test_phase12_part2c_maintenance.py`.
- No Firestore schema change, no new collection, no change to existing endpoint contracts.

**Admin Panel (frontend) — every remaining Part 1D/1C backend module now has a page** (nav entries + route guards; the server still enforces every permission)
- `/admin/orders` — Payment review queue (approve / reject with note / re-verify; screenshot link only if https) + all orders with status / type / user filters.
- `/admin/users` — search, banned filter, user detail, **Ban / Unban** (reason), **access list with expiry**, extend (hours / lifetime), revoke, admin grant. Purchase history is never deleted (revoke only changes the entitlement status).
- `/admin/support` — tickets (filter, reply, status) and **FAQ** CRUD (visible/hidden, order). The Mini App's FAQ endpoint already serves only visible FAQs by order.
- `/admin/notifications` — send to one user / all (Banned excluded server-side, size cap, confirm sheet) + read-only per-user history.
- `/admin/settings` — **Maintenance Mode + message**, app name/logo, display currency, USDT→BDT rate, wallet flag, **Terms URL, Privacy URL**, Support URL / username, bot username. Only changed fields are sent; empty link clears it.
- `/admin/audit` — filterable, read-only audit log with redacted before/after snapshots.
- `/admin/admins` — admin accounts: create, role, activate/deactivate, password reset (Environment super-admin is read-only; you cannot edit your own role/status).
- Shared: `useAdminList` hook (pagination + stale-response guard), `RequireAnyPermission` guard, payment-review methods in `configApi.ts`.

## Integration audit (read-only checks)
- User frontend has no hardcoded price / duration / payment data (scan of `src/` outside `/admin`); price, access duration, packages, banners, sections, ads, payment methods, categories, notifications, FAQ, maintenance, links all come from the API.
- Banned users are rejected on every authenticated request (`get_current_user`), not just at login.
- `firestore.rules` denies all direct client access; every read/write goes through the backend. No Binance / API secret exists in the frontend (existing check `payment-status.check.mts` asserts it).

## Test results (offline)
- Backend `python -m unittest discover -s tests -t .`: 469+ tests; the new Part 2C tests pass. 3 errors are environment-only (`pydantic` / `fastapi` are not installed here: `test_phase7_integration`, two `AppSettings/Homepage` tests); the same modules cannot import in the original ZIP either. Run the full suite once after `pip install -r requirements.txt`.
- Frontend `tests/run-payment-status-check.sh` (57 checks) and `run-rewarded-ad-check.sh` (14 checks) pass. `run-api-client-check.sh` needs `axios` (no `node_modules` offline) — same in the original ZIP.
- New/changed TSX/TS files were syntax-checked with the TypeScript compiler only.

## NOT verified here — please do before go-live
1. `cd video-store-frontend && npm install && npm run build` (full type-check; `@types/react` etc. are unavailable offline).
2. `pip install -r requirements.txt && python -m unittest discover -s tests -t .` in the backend.
3. Live-only (nothing was run against live Firebase / Binance / Telegram, no writes were made): real Telegram initData login, Binance Pay create/verify/webhook, Monetag S2S callback, Firestore composite indexes (`firestore.indexes.json`, `docs/firestore_indexes.md`), real admin login with your `ADMIN_PASSWORD_HASH`.
4. Mobile layout of the new admin pages was written with the same mobile-first classes as the existing pages but not viewed in a browser.

## Known limits (kept honest)
- Terms / Privacy are admin-managed **URLs** (https), not in-app text.
- Admin list endpoints that scan (audit log, user search) are capped by the backend (`scan_cap`); narrow the filters for older records.
- Ads reward only via real provider server-to-server callback; Binance auto-verification only for Binance Pay; others are manual review (unchanged).
