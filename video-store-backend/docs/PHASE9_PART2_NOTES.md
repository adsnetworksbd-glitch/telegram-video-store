# Phase 9 — Part 2 (short)

Done: real Monetag GET-postback verification (secret token, impression+valued only), transactional + idempotent counting,
one-time unlock (entitlement + ledger + audit), crash recovery, ownership/zone checks, log redaction, frontend per-ad unique
`ymid`, "ad not verified → retry" state. Phase 8 access rules untouched (ads = separate source).

Not verified live: a real Monetag postback (macro values / timing / whether `telegram_id` is populated), Firestore
transactions (`async_transactional`) against a real database, `npm run build`, real Android/iOS/Desktop clients.

Notes: valued postbacks can arrive late (UI waits + polls, then offers retry); Monetag's SDK promise resolves even if the user
closes the ad early (never used as proof); one provider only (Monetag). Needs: dashboard Postback URL set per `.env.example`.
