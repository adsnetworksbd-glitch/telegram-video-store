# Video Store API Reference
Base URL: `https://api.videostore.app/api/v1`

All protected endpoints require: `Authorization: Bearer {jwt_token}`

---

## Auth
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/telegram` | ❌ | initData verify → JWT (body: `init_data`, optional `start_param` = referral code `VS-XXXXXXX` from the launch URL; identity always comes from the verified initData) |
| POST | `/auth/refresh` | ❌ | Refresh JWT |

**Auth error behaviour (Phase 8 Part 1)** — request/response shape unchanged; only error text/status changed:

| Situation | Status | `detail` |
|---|---|---|
| initData missing / bad hash / expired / malformed / duplicate field / invalid user | 401 | `Authentication failed` (always the same text; real reason is server-log only) |
| `TELEGRAM_BOT_TOKEN` not configured on the server | 503 | `Authentication unavailable` |
| Account banned (`is_banned` or `account_status == "banned"`) | 403 | `Account banned` (now also enforced at `/auth/telegram`) |
| Missing / invalid / expired JWT on a protected route | 401 | `Not authenticated` / `Invalid or expired token` |

`POST /auth/telegram` creates the Firestore `users/{telegram_id}` document only on the first verified login (atomic `create`), and on later logins writes only `last_login` and `last_seen_at`.

## Config
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/config` | ❌ | App settings |
| GET | `/config/homepage` | ❌ | Homepage section order |

## Videos
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/videos` | ❌ | List (filter, sort, search, page) |
| GET | `/videos/featured` | ❌ | Featured videos |
| GET | `/videos/trending` | ❌ | Trending videos |
| GET | `/videos/latest` | ❌ | Latest videos |
| GET | `/videos/{id}` | ✅ | Detail + access status |
| GET | `/access/video/{id}/source` | ✅ | Decrypted source URL (access required) |

## Categories
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/categories` | ❌ | All visible categories |
| GET | `/categories/{id}` | ❌ | Category + videos |
| GET | `/categories/{id}/videos` | ❌ | Videos in category |

## Packages
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/packages` | ❌ | All packages |
| GET | `/packages/featured` | ❌ | Featured packages |
| GET | `/packages/{id}` | ✅ | Detail + access status |

## Entitlements
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/entitlements` | ✅ | User's entitlements |
| GET | `/entitlements/check/video/{id}` | ✅ | Check video access |
| GET | `/entitlements/check/package/{id}` | ✅ | Check package access |

## Orders & Payments
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/payment-methods` | ❌ | Enabled + payable payment methods (Phase 10: kind, pay_id, merchant_name, limits, auto/manual flags) |
| POST | `/orders` | ✅ | Create order (Phase 10: min/max check, duplicate prevention — an identical open order is returned with `payment_details.reused = true`) |
| GET | `/orders/{id}` | ✅ | Order detail (Phase 10 Part 2B: also `details` = admin-configured screen data, user-safe `timeline[]`, `retry{allowed,remaining}`, `payment.review_code`) |
| POST | `/orders/{id}/submit` | ✅ | Submit transaction hash |
| POST | `/orders/{id}/verify` | ✅ | Binance Pay only: ask Binance (signed API) whether it is paid; throttled; never grants access by itself |
| POST | `/orders/{id}/retry` | ✅ | New order after expired/failed (optional `payment_method_id`); retry cap is an admin setting |
| GET | `/orders/history` | ✅ | Order history |

## Ads
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/ads/session/start` | ✅ | Start ad session |
| POST | `/ads/session/complete` | ✅ | Poll session status |
| POST | `/webhooks/monetag` | ❌ (HMAC) | Monetag S2S callback |

## Coupons
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/coupons/validate` | ✅ | Validate coupon |

## Referral
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/referral/info` | ✅ | Referral code + stats |
| GET | `/referral/history` | ✅ | Referral list |

## User
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/user/profile` | ✅ | Profile |
| GET | `/user/transactions` | ✅ | Transaction history |
| GET | `/user/notifications` | ✅ | Notifications |
| POST | `/user/notifications/read` | ✅ | Mark read |

## Search & Support
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/search?q=` | ❌ | Search videos & packages |
| GET | `/support/faq` | ❌ | FAQ list |
| POST | `/support/ticket` | ✅ | Submit support ticket |

## Webhooks
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/webhooks/binance-pay` | Binance RSA cert (or HMAC) | Trigger only: signature checked, then the order is re-verified with Binance's signed order-query API |
| POST | `/webhooks/monetag` | HMAC | Monetag S2S ad callback |

---

## Error Codes
| Status | Meaning |
|---|---|
| 400 | Bad Request — invalid input |
| 401 | Unauthorized — invalid/expired JWT |
| 403 | Forbidden — no permission |
| 404 | Not Found |
| 409 | Conflict — duplicate (already has access, payment submitted, etc.) |
| 422 | Validation Error |
| 500 | Internal Server Error |

## Security Notes
- JWT stored in Frontend memory only (never localStorage)
- Source URLs AES-256 encrypted at rest in Firestore
- Binance Pay webhooks HMAC-SHA512 verified
- Monetag callbacks HMAC-SHA256 verified
- Ad access only granted after S2S callback (never frontend-only)
- All sensitive keys in Render environment variables only


## Phase 5 additions

### Admin (manual payment review)
All routes except login need `Authorization: Bearer <admin token>` (60 min). User tokens are rejected. `401` = not logged in / token invalid, expired or revoked / account disabled; `403` = role lacks the route's permission.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/admin/login` | `{username,password}` → `{access_token, token_type, expires_in, admin{username,display_name,role,permissions[]}}` (rate limit 5/5min/IP; 5 wrong passwords lock that account 15 min → `429`) |
| GET | `/api/v1/admin/me` | Current admin + permissions (re-checked against Firestore) |
| GET | `/api/v1/admin/payments/pending` | Orders in `under_review` with txhash/screenshot |
| POST | `/api/v1/admin/payments/{order_id}/approve` | Verify payment + fulfill order (idempotent) |
| POST | `/api/v1/admin/payments/{order_id}/reject` | Mark order `failed`, notify user |

### Webhooks (server-to-server, both FAIL CLOSED)
- `POST /api/v1/webhooks/binance-pay` — rejects (403) when `BINANCE_PAY_API_SECRET` is unset or signature missing/invalid. Amount < expected or currency != USDT → order moved to `under_review` (no auto grant). **Signature scheme still unverified against live Binance (see report).**
- `POST /api/v1/webhooks/monetag` — rejects (403) unless `X-Monetag-Signature` = HMAC-SHA256(body, `MONETAG_CALLBACK_SECRET`). Requires `session_id` + unique `ad_id`; expired sessions ignored. **Monetag's real postback format/signing is unverified.**

### Other changes
- `GET /entitlements?status=expired` — `status` is now derived (`expired` when a temporary entitlement is past `expires_at`).
- `AccessStatus.expired` (bool) — true when temporary access existed but ran out.
- Rate limiting: in-memory per-IP sliding window, 429 + `Retry-After` (see `app/core/rate_limit.py` RULES).
- New env: `PUBLIC_API_BASE_URL`, `TELEGRAM_BOT_USERNAME`, `RATE_LIMIT_ENABLED`. Production startup refuses invalid config (`validate_runtime_config`).


## Phase 7 additions (integration fixes — contract is additive)
- **401 for missing token.** `Authorization` header absent → `401 Not authenticated` (was `403` with FastAPI 0.111's `HTTPBearer`). The frontend's refresh-and-retry only reacts to 401.
- **`GET /config`** now also returns optional `terms_url`, `privacy_url`, `support_username`, `support_url` (all `null` unless the admin sets them in `app_settings/config`). Missing/invalid fields in that document fall back to safe defaults instead of a 500.
- **`GET /categories`, `/categories/{id}`**: missing fields in a category document fall back to defaults instead of a 500.
- **`GET /entitlements`** now fills `video` / `package` (batched read) so My Purchases needs no per-row lookups. If the join fails the fields stay `null` (old behaviour).
- **Order expiry (derived).** `GET /orders/{id}` and `GET /orders/history` report `status: "expired"` for an `awaiting_payment` order past `expires_at`; `GET /orders/{id}` also persists it (own order only). A late Binance webhook can still complete such an order. `payment_submitted` / `under_review` are never auto-expired.
- **Firestore indexes:** complete set in `firestore.indexes.json` (`firebase deploy --only firestore:indexes`).

---

## Phase 8 Part 2A — behaviour notes (no route / request / response-shape changes)

- **Malformed catalog documents.** List endpoints (`/videos`, `/videos/featured|trending|latest`,
  `/categories/{id}`, `/categories/{id}/videos`, `/packages`, `/packages/featured`, `/search`) skip a
  Firestore document that fails response validation (e.g. `quality: "720p"`) and log
  `Skipping malformed video/package <id> (invalid fields: …)` instead of answering 500 for the whole list.
  `GET /videos/{id}` and `GET /packages/{id}` answer **404** for such a document. Documents are never modified.
  `total` still counts the skipped documents.
- **`source_type`.** A stored value outside the supported set (`telegram_bot, telegram_channel, google_drive,
  dropbox, direct_mp4, custom_url`) is returned as `custom_url` by `GET /videos/{id}` and
  `GET /access/video/{id}/source` (the app labels that type "may not open / may not be downloadable").
- **`GET /access/video/{id}/source`** now sends `Cache-Control: no-store` (the response carries the protected link).

---

## Phase 8 Part 2 (B-1) — access control (additive; no route or request change)

- **`AccessStatus.active_sources`** (`string[]`, default `[]`) — every access source valid *right now*, best first,
  e.g. `["individual_purchase", "ads_unlock"]`. `source` is still the best one. Each source is a separate
  entitlement record; nothing is merged or deleted. Returned by `GET /videos/{id}`, `GET /packages/{id}`,
  `GET /entitlements/check/video|package/{id}`.
- **One rule set for every access decision** (`app/services/access_rules.py`): lifetime never expires; a temporary
  entitlement is valid only while `expires_at` is in the future; every record is judged on its own, so an expired or
  revoked record never invalidates another valid record. Best = lifetime → latest expiry → paid over ads.
- **Fail closed.** A temporary entitlement with no usable `expires_at`, or a non-`active` / unknown `status`, grants
  nothing. (Before, `check_video_access` treated a temporary entitlement without `expires_at` as valid forever and
  `GET /entitlements` listed it as `active`; both now treat it as not valid / `expired`.)
- **Free needs a published video.** `is_free` only grants access while `is_published` is true. Entitlement holders
  are unaffected.
- **`GET /access/video/{id}/source`** audit entry now records which source granted access (`access_source`,
  `is_lifetime`). Access is checked before the link is decrypted; `403 Access denied` when nothing is valid.
- `user_id` always comes from the verified JWT (`Depends(get_current_user)`); no endpoint accepts it from the client.

---

## Phase 9 Part 1 — ads infrastructure (additive; existing routes and request bodies unchanged)

- **Provider modules** live in `app/services/ad_providers/` (`base.py`, `monetag.py`, `registry.py`). A provider verifies
  its own S2S callback and exposes only public client config. Add a network = new module + one line in `registry.py`
  (+ a matching adapter in `frontend/src/utils/rewardedAd.ts`).
- **Network choice** (`app/services/ad_config.py`): enabled + registered provider + S2S supported + placement allowed +
  required fields present; lowest `priority` first, the rest is the fallback order. No new Firestore index needed.
- **Placements:** `video_unlock`, `package_unlock`, `rewarded`. Sessions use the first two (by content type). `rewarded` is
  reserved architecture: no endpoint grants anything for it yet. A network that lists placements but omits one is not offered for it.
- **Session settings:** `ads_required` / `ads_unlock_duration_hours` come from the content, else the network
  (`default_ads_required`, `unlock_duration_hours`); `session_timeout_minutes` (1–240, default 30) from the network.
  Resolved values are stored on the session (`unlock_duration_hours`, `placement`, `provider_id`, `status`).
  `0` unlock hours = lifetime (existing convention); `ads_required` is never below 1.
- **`POST /ads/session/start`, `/ads/session/complete`** — same request/response; response gains optional
  `status` (`pending|in_progress|completed|expired`), `placement`, `network_config.provider_id`, `network_config.sdk_url` (https only).
- **`POST /webhooks/monetag`** (unchanged URL) and new **`POST /webhooks/ads/{provider_type}`** — signature verified by
  the provider (fail-closed), must match the session's provider, replay-safe by `ad_id`. Only this path can create an entitlement.
- **Admin** (admin JWT): `GET /admin/ad-networks`; `PUT /admin/ad-networks/{id}` (merge update; fields: `name, type, is_enabled,
  priority, zone_id, sdk_url, placements, default_ads_required, unlock_duration_hours, session_timeout_minutes`).
  Secrets are never accepted or returned (only the env-var *name*). Enabling requires the provider's required fields
  (Monetag: `zone_id`). New networks start disabled. Every change is audit-logged. No delete endpoint.

---

## Phase 9 Part 2 — reward verification & unlock (no new collection, no route removed)

**Monetag mechanism (docs.monetag.com → Postbacks).** Monetag calls `GET /api/v1/webhooks/monetag` with query macros
`ymid, event_type, reward_event_type, zone_id, sub_zone_id, estimated_price, request_var, telegram_id`. It sends **no
signature**; the only authentication is the secret token you put in the Postback URL (`MONETAG_CALLBACK_SECRET`, see
`.env.example`). The older `POST` + `X-Monetag-Signature` path is kept as legacy.

- Counted only when `event_type=impression` **and** `reward_event_type=valued`; everything else is acknowledged `200 ignored`.
- `ymid = "<session_id>.<nonce>"` (built by the app per ad event). Session id binds the ad to one backend session; the full
  `ymid` is the idempotency key. `telegram_id` (when sent) must equal the session owner; `zone_id` must equal the network's zone.
- Wrong/missing secret → `403 Invalid callback` (same message for every failure). Unconfigured secret → always rejected.
- Counting runs in a **Firestore transaction** (`decide_callback`): replays are `duplicate`, nothing counts after the threshold,
  expired sessions are rejected and marked `expired`.
- When the threshold is crossed the session gets `grant_pending`, then `_finalize_grant` creates **one** entitlement
  (`ent_ads_<session_id>`, source `ads_unlock`, duration decided by the backend at session start), a ledger row
  (`transactions/ads_<session_id>`, type `ads_unlock`, amount 0), an `ads_unlock_granted` audit entry and the existing
  notification; the session is marked `completed` last. If the process stops in between, the next callback or the user's next
  `POST /ads/session/complete` finishes it idempotently (backend state only; the client can never trigger a grant).
- Other entitlements (paid, package, lifetime) are never read or modified by an ads unlock; each valid source stays valid on its own.
- Webhook rate limit is 600/min per IP for `/api/v1/webhooks/*` (all methods): the callbacks come from the network's servers, not users.
- `secret=`, `key=`, `token=` query values are masked in log output (`app/core/log_redact.py`).

## Phase 10 — Payment methods (admin)
Methods live in the existing `payment_methods` collection (doc ID = unique method ID). Built-in types: `binance_pay`, `binance_id`, `usdt_trc20`, `usdt_bep20`, `usdt_erc20`; any other slug (`^[a-z0-9][a-z0-9_]{1,31}$`) is a free-form "other" method. Binance API secrets stay in env vars — never in these documents.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/admin/payment-methods` | admin | All methods incl. disabled, with `payable` + config `problems` |
| POST | `/admin/payment-methods` | admin | Create (starts disabled unless `is_enabled` is sent; never overwrites an ID) |
| PUT | `/admin/payment-methods/{id}` | admin | Partial update; merged config is validated |
| PATCH | `/admin/payment-methods/{id}/enabled` | admin | Enable/disable (a broken config cannot be enabled) |
| POST | `/admin/orders/expire-stale` | admin | Persist `expired` on overdue unpaid orders (cron-friendly) |

Order creation rules: user from the Telegram-auth JWT; price, USDT amount (admin rate), currency, expiry and status are server-side only. One open order per user+item: same method/coupon/amount → the same order is returned; otherwise the old unpaid order is retired. A payment already `under_review` for the item → `409`. The payment document snapshots wallet / Pay ID / network at creation.


## Phase 10 — Part 2A additions
- Admin: `GET /admin/payments/{order_id}` (order + payment + `status_history`), `POST /admin/payments/{order_id}/reverify` (Binance Pay only), `POST /admin/payments/{order_id}/approve` now accepts optional `paid_amount_usdt` (422 if it does not cover the expected amount). `GET /admin/payments/pending` items include `review_reason`.
- Verification modes: only Binance Pay can be auto (`auto_verification_supported`); admin may switch it to manual (a PAID answer is then held in `under_review`). All other methods are always manual review.
- Payment document (additive): `status_history[]`, `last_checked_at`, `attempts`, `review_reason`, `binance_last_status`. Tx-hash claims are documents `payments/txclaim_<hash>` (`kind: "txhash_claim"`).
- Admin settings in `app_settings/config`: `payment_verify_min_interval_seconds` (default 5), `payment_retry_limit_24h` (default 5).


## Phase 10 — Part 2B additions
- `GET /orders/{id}` (additive fields): `details` (method name, Pay ID / address snapshot, merchant, QR, instructions — from the order snapshot + the admin's method document), `timeline[]` (`{at, step, source}`; admin names and notes are never included), `retry` (`allowed`, `remaining` — `null` = no cap), `payment.review_code` (`user_submitted | amount_mismatch | reference_mismatch | manual_mode | late_payment | other`, only while the order waits for an admin), `payment.attempts`, `payment.last_checked_at`. `GET /orders/history` items carry `payment_method_type`.
- `fulfill_order` is now crash-safe and race-safe: deterministic entitlement `ent_<order>` and ledger row `txn_purchase_<order>` (create-once), the order moves to `completed` in a Firestore transaction that exactly one caller wins, and only the winner updates `purchase_count`, coupon usage and the referral reward. Orders in `failed` / `refunded` can never be fulfilled (a rejected order that is paid later goes back to `under_review` first). `POST /admin/payments/{id}/approve` answers `409` (nothing granted) if fulfilment refused, e.g. a rejection raced the approval.
- `POST /orders/{id}/submit` is serialised per order (double tap → second request gets a clean `409`).
- `record_transaction(..., tx_id=...)` is create-once: a repeat neither duplicates the ledger row nor adds to `total_spent_bdt` twice.

## Phase 12 / Part 1A — Admin roles & permissions
- Accounts: Firestore `admin_users/{username}` (bcrypt `password_hash`, `role`, `is_active`, `token_version`, lockout fields). Create/update with `python scripts/create_admin.py`. The `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` env account still works as a bootstrap `super_admin`.
- Roles: `super_admin` (everything), `admin` (everything except `ads.manage`, `payment_methods.manage`, `settings.manage`, `admins.manage`), `moderator` (`dashboard.view`, `videos.view`, `orders.view`, `users.view`, `support.manage`). Defined in `app/core/admin_roles.py`.
- Role is read from Firestore on every request (not from the token), so role changes, disabling, or a password change (`token_version`) apply immediately.
- Guards: `payments/*` and `orders/expire-stale` → `payments.review`; `ad-networks` → `ads.manage`; `payment-methods` → `payment_methods.manage`. Refused attempts are audit-logged (`admin_permission_denied`).

## Phase 12 / Part 1B — Admin configuration structure
Same admin JWT + role permissions, same Firestore collections (no new collection, no schema change). The Admin Panel renders its forms from `GET /admin/config/schema` (field types, limits, defaults, enums, per-module `can_view` / `can_manage` for the caller's role) — all values come from the backend modules that own the rules (`services/admin_config.py`).

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/admin/config/schema` | any admin | modules `videos`, `packages`, `ads`, `payments` |
| GET / POST | `/admin/videos` | `videos.view` / `videos.manage` | list (`q`, `published`, paging); create starts **unpublished**; ID never overwritten (`409`) |
| GET / PUT | `/admin/videos/{id}` | `videos.view` / `videos.manage` | partial update, merged result validated; GET adds `packages[]` (reverse relation) |
| PATCH | `/admin/videos/{id}/published` | `videos.manage` | cannot publish without a source |
| GET / POST | `/admin/packages` | `videos.view` / `videos.manage` | `video_ids` must exist (max 20); `video_count`, `discount_percentage`, `duration_hours` (lifetime→0) are server-derived |
| GET / PUT | `/admin/packages/{id}` | `videos.view` / `videos.manage` | GET adds `videos[]` (each included video's state) |
| PATCH | `/admin/packages/{id}/published` | `videos.manage` | cannot publish an empty package |
| GET | `/admin/ads-config` | `ads.manage` | networks in fallback order + per-placement readiness (edit via existing `PUT /admin/ad-networks/{id}`) |
| GET | `/admin/ad-networks/{id}/verification` | `ads.manage` | S2S readiness: provider, secret *configured?* (boolean only), problems. Configuration status only — an ad counts solely via a real provider callback |
| GET | `/admin/payment-config` | `payment_methods.manage` | methods (auto/manual, payable), Binance credential readiness (booleans + missing setting names), verification settings |
| GET / PUT | `/admin/payment-settings` | `payment_methods.manage` | `payment_verify_min_interval_seconds` (0–3600), `payment_retry_limit_24h` (0–100) in `app_settings/config` |

- A video's `source_url` is write-only: encrypted into `source_url_encrypted`, never returned (responses carry `has_source`).
- Counters (`view_count`, `purchase_count`) and timestamps are never client-settable.
- Every write is audit-logged. Methods (Binance Pay / ID / USDT networks, manual review, auto verification) keep using the existing `/admin/payment-methods` routes.
- Frontend: `src/admin/configApi.ts` (typed client; no business values).

## Phase 12 / Part 1C — Coupons, referral, homepage, settings, notifications, user access
Same admin JWT + permissions; same collections (no new collection). Field specs / limits are published in `GET /admin/config/schema` (modules `coupons`, `referral`, `homepage`, `settings`, `notifications`, `access`; rules in `services/admin_settings.py`). Every write is audit-logged.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET / POST | `/admin/coupons` | `coupons.manage` | list (`q`, `active`, paging); create starts **inactive**, code unique (`409`) |
| GET / PUT | `/admin/coupons/{id}` | `coupons.manage` | partial update, merged coupon validated; code and `used_count` never change |
| PATCH | `/admin/coupons/{id}/active` | `coupons.manage` | |
| GET | `/admin/coupons/{id}/usage` | `coupons.manage` | per-use records |
| GET / PUT | `/admin/referral-settings` | `settings.manage` | `referral_enabled`, `referral_reward_type` (only `coupon`), `referral_reward_amount`, `referral_fraud_cooldown_hours`, `referral_coupon_valid_days` (new; default 7 = previous fixed value) |
| GET | `/admin/referrals` | `users.view` | filter `status`, `referrer_id` |
| GET / PUT | `/admin/homepage` | `settings.manage` | `sections` (ids from the Home page, order), `banners` (≤10: image, link, window, order), announcement + link |
| GET / PUT | `/admin/app-settings` | `settings.manage` | name, logo, **maintenance mode + message** (enforced by the Mini App via `/config`; API calls are not blocked), USDT rate (new orders only), wallet flag, legal/support links |
| GET / POST | `/admin/notifications`, `/notifications/send`, `/notifications/config` | `notifications.send` | send to one user or all non-banned users (≤5000, batched); types `announcement|promo|system`; actions `open_video|open_package` |
| GET | `/admin/users/{uid}/access` | `users.view` | entitlements with derived state (`active|expired|revoked`) |
| POST | `/admin/entitlements/grant` | `users.manage` | `access_source=admin_grant`, `duration_hours` (0 = lifetime) |
| POST | `/admin/entitlements/{id}/revoke`, `/extend` | `users.manage` | extend adds hours from the later of current expiry / now, or `lifetime:true`; revoked cannot be extended (`409`) |
| PATCH | `/admin/users/{uid}/banned` | `users.manage` | effective on the user's next request |

- `GET /config/homepage` is additive: `banners[]` (enabled, inside their window, sorted; unsafe links dropped). `sections` is unchanged. The Home page does not render banners yet (UI is a later part).
- Client: `src/admin/configApi.ts`.


## Phase 12 / Part 1D — Dashboard, orders, users, support, audit log, categories, admin accounts
Same admin JWT + permissions; same collections (no new collection). Field specs / enums are published in `GET /admin/config/schema` (modules `dashboard`, `orders`, `users`, `support`, `audit`, `categories`, `admins`, version `12.1d`; rules in `services/admin_ops.py`). Every write is audit-logged. Read views are whitelists; audit snapshots are redacted (password / token / hash / secret / source-URL keys → `[redacted]`).

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/admin/dashboard` | `dashboard.view` | orders (30-day window, ≤5000 read): by status, today, awaiting review, revenue (`completed` only: today / 7d / 30d; `truncated` flag), counts of users / videos / packages / open tickets. A count that cannot be read is `null` (show "—"), never `0` |
| GET | `/admin/orders`, `/orders/{id}` | `orders.view` | filters `status`, `user_id`, `content_type`; detail adds payment rows (no screenshots / hashes). Approve / reject stays on `/admin/payments/*` |
| GET | `/admin/transactions` | `orders.view` | ledger; filters `user_id`, `type`, `direction` |
| GET | `/admin/users`, `/users/{uid}` | `users.view` | list: `q` (id / @username / name), `banned`; detail: profile, access summary (active / expired / revoked), last 20 orders & transactions. Ban / access: Part 1C routes |
| GET | `/admin/support/tickets`, `/{id}` | `support.manage` | filters `status`, `user_id` |
| POST | `/admin/support/tickets/{id}/reply` | `support.manage` | saves `admin_reply`, sets status (default `resolved`), sends the user a `system` notification |
| PATCH | `/admin/support/tickets/{id}/status` | `support.manage` | `open|in_progress|resolved|closed`; resolved/closed stamp `resolved_at`, re-open clears it |
| GET / POST / PUT / DELETE | `/admin/faqs[/{id}]` | `support.manage` | question, answer, display_order, is_visible (used by `GET /support/faq`) |
| GET | `/admin/audit-logs` | `audit.view` | filters `action`, `performed_by`, `target_type`, `target_id`, `since`, `until`; newest-first over the latest 2000 entries (`scan_cap`) |
| GET / POST / PUT | `/admin/categories[/{id}]` | `videos.view` / `videos.manage` | create starts **hidden**; ID and slug unique (`409`); partial update, merged result validated |
| POST | `/admin/categories/{id}/recount` | `videos.manage` | stores the real published-video count in `video_count` (the public app shows that stored value) |
| GET / POST | `/admin/admins` | `admins.manage` | list never returns hashes / token versions; env bootstrap account listed as `source: env` (read-only) |
| PUT | `/admin/admins/{username}` | `admins.manage` | role / display name / active; a role or active change signs the account out immediately |
| POST | `/admin/admins/{username}/password` | `admins.manage` | new password (10–72 bytes, bcrypt, never returned or logged); signs out sessions, clears lockout |

- Safety: an admin cannot change their **own** role / active flag, and the last active super admin can never be demoted or disabled (`409`).
- New Firestore indexes (deploy `firestore.indexes.json`): `orders(status, created_at↓)`, `support_tickets(status, created_at↓)`, `support_tickets(user_id, created_at↓)`.
- Client: `src/admin/configApi.ts` (`dashboard`, `orders`, `users`, `tickets`, `faqs`, `auditLogs`, `categories`, `admins`, …).
- Not in Part 1D (UI is a later part): the admin screens themselves.

## Phase 12 / Part 2A — Admin Panel UI (login, dashboard, videos, categories)
Frontend: `/admin` (own login, outside the Telegram AuthGate) → `src/admin/` (`AdminLayout`, `pages/Dashboard|Videos|VideoForm|Categories`). Every page sits behind `<RequirePermission>`; the server enforces the same permission on each call. Forms render limits / enums / defaults from `GET /admin/config/schema`.

Backend additions (all additive; no schema change, no new collection or index):
- **Backup source** — `videos` accept `backup_source_type` (same enum as `source_type`) and write-only `backup_source_url` (https; stored encrypted as `backup_source_url_encrypted`; `""` removes it). Admin video views return only `has_backup_source` (boolean). Never audited or returned in plain form.
- `GET /access/video/{id}/source?backup=true` — same access check as before, returns the backup link (`404` if none). Without the parameter the response is unchanged. The Mini App does not call it yet.
- `GET /admin/dashboard` — adds `users.banned`; `catalog.videos_hidden|videos_featured|videos_trending|categories_total|categories_visible`; and role-gated lists `top_videos` (`videos.view`), `recent_orders` (`orders.view`), `recent_activity` (`audit.view`, redacted). A list the role may not see, or that failed to load, is `null`.
- **Archive** = hide: `PATCH /admin/videos/{id}/published {is_published:false}`. There is deliberately no hard delete (orders, entitlements and packages reference videos).
