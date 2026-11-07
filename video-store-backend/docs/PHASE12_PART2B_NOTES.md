# Phase 12 — Part 2B notes

Done (Admin Panel frontend; no backend or API contract change, no new Firestore collection):
- `/admin/packages`, `/admin/packages/new`, `/admin/packages/:id` — package list (Publish/Hide, Featured), create/edit (thumbnail URL + preview, included videos with search/reorder/remove, price + original price → discount preview, Lifetime/Custom duration, Ads Unlock + required ads, Purchase on/off, Featured, Publish, display order). A video can sit in any number of packages.
- `/admin/homepage` — section visibility + order + labels, banners (add/remove/reorder, link to video/package/URL, schedule), announcement + link. Featured / Trending / Latest videos and Featured packages are driven by the flags on the video and package forms; Popular categories by visible categories.
- `/admin/ads` — ad networks: create/edit/enable/disable, priority, placements, required ads, unlock duration, session timeout, readiness (secret configured? S2S supported?) and per-placement fallback order.
- `/admin/payments` — payment methods (Binance Pay, Binance ID, USDT TRC20/BEP20/ERC20, custom methods): wallet / Pay ID, network, QR, instructions, min/max, timeout, Auto vs Manual, enable/disable; Binance credential readiness; verification settings; expire-stale-orders sweep.
- `/admin/coupons` — list/search/filter, create/edit, activate/deactivate, percentage / fixed, usage limits, expiry, applicable videos/packages (searchable), usage history.
- `/admin/referral` — enable/disable, reward amount, reward coupon validity, fraud cooldown (min referred-account age), referral list by status.
- Nav + routes + permission guards added (videos.view/manage, settings.manage, ads.manage, payment_methods.manage, coupons.manage). The server still enforces every permission.

Honest limits (kept on purpose):
- Ads: a reward is only ever granted by a real provider server-to-server callback (backend `ads.py`). The panel shows configuration readiness only; it never marks an ad as verified. Callback secrets live in server env vars and are never shown or stored by the panel. Only providers registered in the backend (currently Monetag) can be selected; another network needs a provider module first.
- Payments: only Binance Pay has an API verifier. Wallet / Pay ID / custom methods are always Manual Review (the server rejects `auto_verification_supported` for them). Binance API keys are server env vars, never stored by the panel.
- Referral: reward type is `coupon` only (what `referral.py` issues). Self-referral, duplicate referral and one-reward-per-referral are enforced in the backend and listed read-only in the panel. `referral_min_purchase_required` is read by the backend but was never part of the admin schema; left untouched.
- Thumbnails / banners are https URLs (no file storage service exists).
- Package list has no text search (the backend list endpoint has none).

Not verified here: `npm install && npm run build` / `tsc` (no network, `@types/react` not available offline). The new TSX files were syntax-checked with the TypeScript compiler only; run `npm run build` once before deploying. Backend untouched; its tests were not re-run.

Next — Part 2C / 3: continue Phase 12 per the Part 2C prompt. Backend endpoints that have no Admin UI page yet (candidates, confirm against the Part 2C prompt): orders + payment review (`/admin/orders`, `/admin/payments/*`), users + access/ban (`/admin/users*`, `/admin/entitlements/*`), support tickets + FAQ, notifications, app settings, audit logs, admin accounts.
