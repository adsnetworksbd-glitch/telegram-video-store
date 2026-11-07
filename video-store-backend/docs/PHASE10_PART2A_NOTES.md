# Phase 10 — Part 2A (short)

Done: Binance Pay auto-verification via Binance's signed order-query API (webhook, user "check payment" and admin re-verify
share one idempotent verifier); amount/currency/order-reference checks; mismatch, manual mode, or paid-after-rejection → `under_review`,
never access; payment status history; atomic tx-hash claims (+ per-network hash format); retry endpoint with admin-set cap;
verify throttle; admin detail / re-verify / approve-with-amount; Binance checkout window = our order window.
Access is still granted only by `fulfill_order` (deterministic entitlement id). All limits come from Firestore.

Offline-tested only (43 new tests): decision rules, orchestration on an in-memory fake Firestore, RSA check with a local key pair,
source-level security contract. NOT verified live: real Binance order-query response fields, Binance's real webhook signature
format / certificates endpoint, real Firestore transactions, `app/schemas` import (pydantic not installed in the sandbox).

Found, not changed: (1) Part 1 verified webhooks with HMAC-SHA512 + API secret; Binance signs webhooks with its own RSA key,
so real webhooks would have been rejected — now RSA (or HMAC) + authoritative re-query. (2) `fulfill_order`: a crash between creating the
entitlement and updating the order leaves the order un-completed (user has access; no ledger entry) — worth a recovery pass in testing.
(3) Lazy expiry (GET /orders/:id) does not write payment history; the sweep does. (4) Frontend not touched: `/verify` and `/retry` wait for Part 2B.
