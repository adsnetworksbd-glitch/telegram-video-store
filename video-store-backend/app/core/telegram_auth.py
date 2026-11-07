"""
Telegram Mini App initData verification — pure standard library.

Kept free of app/third-party imports so the exact code that runs in production
can be unit-tested with a real HMAC computation (no stubs).

Official algorithm (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
  1. Parse initData as a URL-encoded query string.
  2. Remove `hash`; sort the remaining `key=value` pairs; join with "\\n".
  3. secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  4. expected   = HMAC_SHA256(key=secret_key, msg=data_check_string) (hex)
  5. Constant-time compare with the received hash.

On top of the official steps this module also:
  * rejects duplicate fields (a signed payload from Telegram never has them),
  * requires a numeric `auth_date` and rejects expired / future-dated data,
  * requires a `user` object with a positive integer `id`,
  * compares hashes as bytes (str compare_digest raises TypeError on non-ASCII
    input, which would turn a forged hash into an HTTP 500).

Every failure raises TelegramAuthError carrying a short machine `reason`.
The reason is for SERVER LOGS ONLY — callers must not return it to clients.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse

DEFAULT_MAX_AGE_SECONDS = 86400      # 24 h (same as the pre-Phase-8 behaviour)
MAX_FUTURE_SKEW_SECONDS = 300        # tolerate small clock drift, nothing more
MAX_INIT_DATA_LENGTH = 8192


class TelegramAuthError(ValueError):
    """initData is not acceptable. `.reason` is a log-only code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TelegramAuthConfigError(RuntimeError):
    """Server is misconfigured (e.g. no bot token). Not the client's fault."""


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> dict:
    """
    Validate initData and return the Telegram user dict plus `start_param`.
    Raises TelegramAuthError (client problem) or TelegramAuthConfigError.
    """
    if not bot_token:
        raise TelegramAuthConfigError("bot token not configured")
    if not isinstance(init_data, str) or not init_data:
        raise TelegramAuthError("missing_init_data")
    if len(init_data) > MAX_INIT_DATA_LENGTH:
        raise TelegramAuthError("init_data_too_long")

    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    except ValueError:
        raise TelegramAuthError("malformed_init_data") from None

    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise TelegramAuthError("duplicate_field")

    fields = dict(pairs)
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("missing_hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    # bytes compare: str compare_digest raises TypeError for non-ASCII input.
    if not hmac.compare_digest(expected_hash.encode(), received_hash.encode("utf-8")):
        raise TelegramAuthError("hash_mismatch")

    # ── Signature is valid; now validate the signed content ──────────────────
    raw_auth_date = fields.get("auth_date")
    if raw_auth_date is None:
        raise TelegramAuthError("missing_auth_date")
    if not (raw_auth_date.isascii() and raw_auth_date.isdigit()):
        raise TelegramAuthError("invalid_auth_date")
    auth_date = int(raw_auth_date)

    current = time.time() if now is None else now
    age = current - auth_date
    if age > max_age_seconds:
        raise TelegramAuthError("expired")
    if age < -MAX_FUTURE_SKEW_SECONDS:
        raise TelegramAuthError("auth_date_in_future")

    user_json = fields.get("user")
    if not user_json:
        raise TelegramAuthError("missing_user")
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        raise TelegramAuthError("invalid_user_json") from None
    if not isinstance(user, dict):
        raise TelegramAuthError("invalid_user")
    uid = user.get("id")
    if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
        raise TelegramAuthError("invalid_user_id")

    result = dict(user)
    result["start_param"] = fields.get("start_param")
    return result
