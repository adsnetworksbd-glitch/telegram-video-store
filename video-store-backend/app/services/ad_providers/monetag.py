"""Monetag provider.

REAL Monetag mechanism (docs.monetag.com → Postbacks, checked Nov 2026):
  * Monetag calls OUR URL with an HTTP GET and fills macros into the query
    string: {ymid} {event_type} {reward_event_type} {zone_id} {sub_zone_id}
    {estimated_price} {request_var} {telegram_id}.
  * There is NO signature header. The only authentication available is a secret
    token that WE put into the Postback URL configured in the Monetag dashboard
    (`...&secret=<MONETAG_CALLBACK_SECRET>`); we compare it in constant time.
  * `event_type` is `impression` (ad started rendering) or `click`;
    `reward_event_type` is `valued` or not valued. Only impression + valued counts.
  * `ymid` is whatever the app passed to the SDK; Monetag wants it UNIQUE per ad
    event. We use "<session_id>.<nonce>": the session id binds the ad to one
    backend session, the nonce makes every ad event distinct (idempotency key).
  * `telegram_id` is auto-collected by Monetag and MAY be empty; when present it
    must equal the session owner.

Still unverified live (no network / no Monetag account here): the exact macro
values on a real postback. Legacy: the earlier POST + `X-Monetag-Signature`
(HMAC-SHA256 over the raw body) path from Phase 8/9-Part-1 is kept working; it
is NOT something Monetag documents.
"""
from __future__ import annotations

import hmac
import json
import re
from typing import Mapping

from app.core.webhook_utils import verify_hmac_sha256_hex
from app.services.ad_providers.base import AdProvider, CallbackEvent, CallbackRejected

_SESSION_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")
_YMID_RE = re.compile(r"^([0-9a-fA-F-]{32,36})(?:\.[A-Za-z0-9]{4,40})?$")


def _token_ok(secret: str, token: str) -> bool:
    """Fail CLOSED: no configured secret or no token → never accepted."""
    if not secret or not token:
        return False
    return hmac.compare_digest(secret.encode("utf-8"), token.encode("utf-8"))


class MonetagProvider(AdProvider):
    type = "monetag"
    display_name = "Monetag"
    supports_s2s = True
    secret_setting = "MONETAG_CALLBACK_SECRET"
    required_fields = ("zone_id",)

    # ── real Monetag GET postback ───────────────────────────────────────────
    def _verify_query(self, secret: str, q: Mapping[str, str]) -> CallbackEvent:
        if not _token_ok(secret, q.get("secret") or q.get("key") or ""):
            raise CallbackRejected(403, "Invalid callback")
        if (q.get("event_type") or "").lower() != "impression":
            raise CallbackRejected(200, "event ignored")
        if (q.get("reward_event_type") or "").lower() != "valued":
            raise CallbackRejected(200, "not a valued impression")
        ymid = (q.get("ymid") or "").strip()
        m = _YMID_RE.match(ymid)
        if not m:
            raise CallbackRejected(200, "no session_id")
        tg = (q.get("telegram_id") or "").strip()
        zone = (q.get("zone_id") or "").strip()
        return CallbackEvent(
            session_id=m.group(1),
            ad_id=ymid,
            telegram_id=tg if tg.isdigit() else None,
            zone_id=zone or None,
        )

    # ── legacy POST/HMAC (kept for compatibility, see module docstring) ─────
    def _verify_legacy(self, secret: str, headers: Mapping[str, str], body: bytes) -> CallbackEvent:
        sig = headers.get("X-Monetag-Signature") or headers.get("x-monetag-signature") or ""
        if not verify_hmac_sha256_hex(secret, body, sig):
            raise CallbackRejected(403, "Invalid signature")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            raise CallbackRejected(400, "Invalid JSON") from None
        if not isinstance(payload, dict):
            raise CallbackRejected(400, "Invalid JSON")

        custom = payload.get("custom_data")
        custom = custom if isinstance(custom, dict) else {}
        session_id = payload.get("session_id") or custom.get("session_id")
        ad_id = payload.get("ad_id") or payload.get("transaction_id")
        if not isinstance(session_id, str) or not session_id or "/" in session_id:
            raise CallbackRejected(200, "no session_id")
        if isinstance(ad_id, bool) or not isinstance(ad_id, (str, int)):
            ad_id = None
        return CallbackEvent(session_id=session_id, ad_id=str(ad_id) if ad_id is not None else None)

    def verify_callback(
        self,
        secret: str,
        headers: Mapping[str, str],
        body: bytes,
        query: Mapping[str, str] | None = None,
    ) -> CallbackEvent:
        if query and any(k in query for k in ("ymid", "event_type", "reward_event_type")):
            return self._verify_query(secret, query)
        return self._verify_legacy(secret, headers, body)
