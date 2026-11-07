# PHASE 5 — Final Report (বাংলা)

## অবস্থা: **Phase 5 কোড-লেভেলে সম্পন্ন, কিন্তু Runtime যাচাই অসম্পূর্ণ** (সম্পূর্ণ "PASS" ঘোষণা করা হচ্ছে না)

**কারণ:** এই Environment-এ Network নেই → `pip`/`npm install` অসম্ভব। FastAPI Startup, pytest, `tsc`, Vite Build, Live Binance/Monetag/Firebase কিছুই চালানো যায়নি।

**Part 1 সম্পর্কে:** আপনার উল্লেখ করা `PHASE5_PART1_*` রিপোর্ট/ZIP পৌঁছায়নি। আপলোডে শুধু আসল ZIP ছিল। তাই Part 1+Part 2 একত্রে এই ZIP-এর ওপর করা হয়েছে; কোড দেখে যাচাই করেছি।

## Part 2-এর ১৩ কাজ
| # | কাজ | অবস্থা |
|---|---|---|
| 1 | Frontend↔Backend Integration | ✅ Static (Test); ❌ Runtime নয় |
| 2 | Auth/JWT | 🔧 Refresh (Frontend), User/Admin Token আলাদা; ❌ RS256 Runtime Test নয় (`python-jose` নেই) |
| 3 | Order lifecycle | 🔧 Route-order, Resubmit, Binance-fail ফিক্স; ❌ Firestore ছাড়া চালানো যায়নি |
| 4 | Binance Webhook কোড | 🔧 Fail-closed, Amount/Currency check। ⚠️ Signature পদ্ধতি অযাচাইকৃত |
| 5 | USDT Manual + Admin Review | 🔧 Backend: login/pending/approve/reject। Submit-এ txhash বা screenshot বাধ্যতামূলক। ❌ Admin UI নেই |
| 6 | Monetag কোড | 🔧 Fail-closed, `ad_id` বাধ্যতামূলক, Session expiry। ⚠️ Format অযাচাইকৃত |
| 7 | Entitlement duplicate prevention | 🔧 `ent_<order_id>` + `create()`; Ads-এ Entitlement এখনো Random ID (Session একবারই complete হয়, কিন্তু Atomic নয় — নিচে) |
| 8 | Package vs Video access | ✅ Code Review: একই Expiry নিয়ম, Package → `array_contains`। ⚠️ Package-এ পরে যোগ হওয়া Video পুরনো Entitlement-এ নেই (Snapshot) |
| 9 | Rate limit + Input validation | 🔧 Limiter + সব Request Model-এ Length/Pattern/Range Bound। Unit Test PASS; HTTP-তে নয় |
| 10 | Env/Deploy config | 🔧 `validate_runtime_config`, `render.yaml` আপডেট, Secret Files নির্দেশ (`docs/firestore_indexes.md`) |
| 11 | Firestore access/integrity | 🔧 Coupon usage, Race-safe Fulfillment, `purchase_enabled`/`is_published` check, নতুন Index তালিকা। ❌ Emulator-এ চালানো হয়নি |
| 12 | Offline Test | ✅ ২১টি, সব PASS |
| 13 | Part 1-এর Critical বাকি | ❓ রিপোর্ট না থাকায় নির্ধারণ অসম্ভব |

## Critical ফিক্স (মোট)
Monetag/Binance Webhook Fail-open, Binance Amount যাচাই, Double Entitlement Race, Binance ব্যর্থ হলে অপরিশোধযোগ্য Order, Coupon Usage Record না হওয়া, Admin/User Token মিশ্রণ, Order Submit Duplicate, `/orders/history` Shadowing, Expired Status কখনো তৈরি না হওয়া, `purchase_enabled`/Unpublished Content-এ Order/Ads Session, Unbounded Input।

## অসম্পূর্ণ / ঝুঁকি (লুকানো নেই)
1. ⚠️ **Binance Signature:** HMAC-SHA512 ধরা; আসলে RSA Certificate হতে পারে → ভুল হলে সব Webhook 403 (নিরাপদ, Auto-payment বন্ধ; Manual Review চলবে)। Sandbox লাগবে।
2. ⚠️ **Monetag:** JSON+HMAC ধরে নেওয়া; আসল Postback Docs মেলাতে হবে।
3. ⚠️ **Ads Entitlement Race:** একই Session-এ দুটি Callback একসাথে এলে ২টি Entitlement সম্ভব (Count Read-then-write)। কম ঝুঁকি, Phase 6-এ Transaction/Deterministic ID।
4. ⚠️ **Render:** `.pem`/Firebase JSON Secret File হিসেবে না দিলে Production Boot হবে না (ইচ্ছাকৃত Fail-fast)।
5. ⚠️ Rate Limiter In-memory; Admin Login ৫/৫মিনিট/IP।
6. ⚠️ `/auth/refresh` ≤২৪ ঘণ্টা পুরনো `initData` লাগে।
7. ❌ Telegram Web/Browser UI, Expired Badge দৃশ্য যাচাই হয়নি।
8. ❌ Live Credentials নেই → কোনো Live Verification হয়নি; Firebase-এ কোনো Write করা হয়নি।

## Phase 5 সম্পূর্ণ ঘোষণার শর্ত (আপনার মেশিনে)
`pip install -r requirements.txt pytest` → `uvicorn app.main:app` (Startup) → `python -m unittest tests.test_static_contract` → `npm install && npm run build` → Binance Sandbox + Monetag Test Callback। এগুলো PASS হলে Phase 5 সত্যিকার অর্থে সম্পূর্ণ।
