# Phase 10 — Part 2B (Binance payment: Frontend + final integration)

## What was done
**Backend (additive; Part 2A logic untouched)**
- `services/fulfillment.py` — crash-safe / race-safe fulfilment (fixes the Part 2A "found, not changed" item 2): resumes after a half-finished run, one ledger row, one completion winner, side effects only by the winner, never fulfils `failed`/`refunded`.
- `services/transaction.py` — `tx_id` ⇒ create-once (no double ledger row / `total_spent_bdt`).
- `services/order_view.py` (new, pure) — user-safe `review_code`, `timeline`, `retry_info`.
- `GET /orders/{id}` now returns `details`, `timeline`, `retry`, `payment.review_code` (all from Firestore; no admin notes/names). `submit` serialised per order. Admin approve refuses to report success when nothing was granted.

**Frontend**
- `api`: `ordersApi.verify`, `ordersApi.retry`, typed `detail`.
- `hooks/useVerifyPayment.ts` — "check my payment" (+ background re-check while waiting for Binance), 429 cooldown, double-tap guard.
- `Payment` page: method name / Pay ID / merchant / QR / instructions from the Backend `details`; per-network hash check; Binance check calls `/verify`.
- `PaymentPending`: manual-review reason, Binance re-check + countdown, verification timeline.
- `PaymentFailed`: Retry → `POST /orders/:id/retry` (new order, optional other method, admin cap shown); Binance Pay "I paid late" re-check.
- `Purchase`: double-submit guard, "existing order reused" notice.
- `utils/orderStage.ts`, `utils/paymentStatus.ts` — pure, tested.

## Rules that hold (and are tested)
Frontend never decides success (`completed` is the only path to the Success screen; verify/retry answers come from the Backend). No wallet address, price, secret or method list in the frontend. Access is granted only by `fulfill_order`, from a Binance-API-confirmed exact payment or an admin approval. Manual review stays `under_review` until an admin acts; rejected ⇒ no access; approval ⇒ one purchase + one entitlement.

## Tests (all offline)
- Backend: `tests/test_phase10_part2b_integration.py` (20) — real `fulfillment.py`/`transaction.py` on an in-memory fake Firestore: repeat calls, 6 concurrent callers, crash-after-entitlement, crash-after-ledger, rejected/refunded, lifetime/custom duration, user-safe view, source contracts.
  Whole suite: `python3 -m unittest discover -s tests -t .` → 313 run, 1 error (`test_phase7_integration` — same error as in the Part 2A ZIP, unrelated), 7 skipped (pre-existing).
- Frontend: `sh tests/run-payment-status-check.sh` (57 checks). `tests/run-api-client-check.sh` needs `npm install` and was NOT run here.

## NOT verified / still open (be explicit before go-live)
1. **No live Binance** and **no real Firestore** were available: real order-query fields, webhook signature/cert format, real transaction retry behaviour and Firestore query indexes are untested. Run a Binance sandbox/small-amount test.
2. **Frontend was not built or type-checked with the real dependencies** (no `node_modules`, no network). I type-checked against stubbed modules and compared with the original ZIP: no new errors in the logic/types; run `npm install && npm run build` first.
3. `app/schemas` could not be imported (pydantic missing); the schema edits are additive and syntax-checked only.
4. Purchase counters / coupon usage / referral are best effort *after* access is granted: if the process dies between "order completed" and those steps, access is correct but a counter or reward can be missed (no retry job). 
5. Auto re-check of Binance orders runs only from an open user screen, the webhook, or admin re-verify — there is no server-side scheduler.
6. No UI for admin approve/reject exists in this project (API only), as in Part 2A.
7. Late payment on an `expired` order is honoured (Part 2A rule); the user can trigger it from the Failed screen.
