"""
User identity for Telegram login.

Rules enforced here (Phase 8 Part 1):
  * The user's identity comes ONLY from verified Telegram data (tg_user is the
    output of verify_telegram_init_data) — never from client-supplied fields.
  * Document id == str(telegram user id). A returning user is never recreated.
  * A first login uses Firestore `create()` (fails if the document exists), so a
    race between two simultaneous first logins can never overwrite a document
    that already holds a balance / referral history.
  * A returning login writes ONLY `last_login` and `last_seen_at`. Balance,
    purchases, transactions, referral data and profile fields are left alone.
"""
from __future__ import annotations

import random
import string
from datetime import datetime

try:  # google-api-core ships with firebase-admin; fallback keeps the module importable in minimal test envs
    from google.api_core.exceptions import AlreadyExists
except ImportError:  # pragma: no cover
    class AlreadyExists(Exception):  # type: ignore[no-redef]
        """Stand-in used only when google-api-core is not installed."""

USERS_COLLECTION = "users"  # must equal app.db.firebase.Col.USERS

ACCOUNT_ACTIVE = "active"
ACCOUNT_BANNED = "banned"


def is_blocked(user_data: dict) -> bool:
    """True if the account may not log in / call protected APIs.

    `is_banned` is the pre-existing flag; `account_status` is the Phase 8 field.
    Documents created before Phase 8 have no `account_status`, so a missing value
    is simply treated as 'not blocked by status' (no migration needed).
    """
    return bool(user_data.get("is_banned")) or user_data.get("account_status") == ACCOUNT_BANNED


def _gen_referral_code() -> str:
    return "VS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=7))


async def _unique_referral_code(db) -> str:
    from google.cloud.firestore_v1.base_query import FieldFilter

    while True:
        code = _gen_referral_code()
        q = db.collection(USERS_COLLECTION).where(filter=FieldFilter("referral_code", "==", code)).limit(1)
        if not [d async for d in q.stream()]:
            return code


def _build_new_user(tg_user: dict, referral_code: str, now: datetime) -> dict:
    user_id = str(tg_user["id"])
    start_param = tg_user.get("start_param") or ""
    referred_by = start_param if start_param.startswith("VS-") else None
    return {
        "id": user_id,
        "telegram_id": user_id,
        "username": tg_user.get("username"),
        "first_name": tg_user.get("first_name", ""),
        "last_name": tg_user.get("last_name"),
        "photo_url": tg_user.get("photo_url"),
        "language_code": tg_user.get("language_code", "en"),
        "wallet_balance": 0.0,
        "total_spent_bdt": 0.0,
        "referral_code": referral_code,
        "referred_by_code": referred_by,
        "referral_count": 0,
        "referral_reward_total_bdt": 0.0,
        "account_status": ACCOUNT_ACTIVE,
        "is_banned": False,
        "ban_reason": None,
        "ban_expires_at": None,
        "created_at": now,
        "last_login": now,
        "last_seen_at": now,
    }


async def find_or_create_user(db, tg_user: dict, now: datetime) -> tuple[dict, bool]:
    """
    Returns (user_data, created). Performs NO write for an existing user.
    """
    user_id = str(tg_user["id"])
    ref = db.collection(USERS_COLLECTION).document(user_id)

    snap = await ref.get()
    if snap.exists:
        return snap.to_dict() or {}, False

    new_user = _build_new_user(tg_user, await _unique_referral_code(db), now)
    try:
        await ref.create(new_user)  # atomic: raises AlreadyExists, never overwrites
    except AlreadyExists:
        snap = await ref.get()
        return snap.to_dict() or {}, False
    return new_user, True


async def record_login(db, user_id: str, now: datetime) -> dict:
    """Touch only the two login timestamps of an existing user."""
    fields = {"last_login": now, "last_seen_at": now}
    await db.collection(USERS_COLLECTION).document(user_id).update(fields)
    return fields
