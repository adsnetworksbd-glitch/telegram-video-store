# Phase 6 Handoff

## Gate (Phase 5 সত্যিকার সম্পূর্ণ করতে, আপনার মেশিনে)
1. `pip install -r requirements.txt pytest` → `uvicorn app.main:app` → `/health`।
2. `python -m unittest tests.test_static_contract` (21 Test)।
3. `npm install && npm run build` — `tsc` Error ঠিক করুন (এখানে কখনো চলেনি)।
4. Firestore Emulator + `httpx.AsyncClient` Integration Test: create_order → submit → admin approve → entitlement; Webhook Duplicate/Amount-mismatch; Monetag Replay; Pydantic Validation (প্যাটার্নে বৈধ Firestore ID আটকায় কিনা)।
5. **Binance Sandbox:** Signature পদ্ধতি (RSA Certificate বনাম HMAC) নিশ্চিত করে `services/binance.py: verify_binance_webhook` ঠিক করুন।
6. **Monetag Docs** অনুযায়ী `ads.py: monetag_webhook` মিলান।

## Admin
`/api/v1/admin/login`, `/payments/pending`, `/payments/{id}/approve|reject`। `.env`: `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` (bcrypt)। Admin UI নেই → Phase 6।

## Deploy (Render)
Render Secret Files-এ `private.pem`, `public.pem`, `firebase-service-account.json` দিন; পাথর `/etc/secrets/...` (বিস্তারিত `docs/firestore_indexes.md`)। নতুন Env: `PUBLIC_API_BASE_URL`, `TELEGRAM_BOT_USERNAME`, `RATE_LIMIT_ENABLED`। নতুন Firestore Index যোগ করুন (entitlements `user_id+created_at`, `user_id+content_type+created_at`)।

## Non-critical (Final Stabilization)
Ads Entitlement Atomicity (Deterministic ID `ent_ads_<session>`), purchase_count/Referral Counter Race, Redis Rate-limit, Package-এ নতুন Video Sync, Pagination Cursor, Admin UI, Telegram Web Manual Test, ZIP-এর ফাঁকা `{app/...` Folder পরিষ্কার।

## পরিবর্তিত ফাইল
Backend: `core/{security,deps,config,rate_limit,webhook_utils}.py`, `main.py`, `endpoints/{orders,ads,misc,admin}.py`, `services/{entitlement,fulfillment}.py`, `schemas/__init__.py`, `router.py`, `.env.example`, `render.yaml`, `docs/*`, `tests/`। Frontend: `api/client.ts`, `types/index.ts`, `components/access/index.tsx`, `pages/Auth/index.tsx`।
