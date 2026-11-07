"""
User-facing view of an order's payment state (Phase 10 Part 2B).

Pure functions — no Firestore / network. The payment document holds internal
data (admin notes, admin names, raw Binance reasons). The user's screens get
only a coarse, safe projection of it:

* `review_code`  — WHY an order is waiting for an admin (no amounts, no notes)
* `timeline`     — status changes with a coarse source label (no admin names / notes)
* `retry_info`   — whether the user may start a new order and how many tries are left
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# review_reason (internal, set by payment_verification) → coarse public code
_REVIEW_CODES = {
    "paid_amount_or_currency_mismatch": "amount_mismatch",
    "paid_amount_unreadable": "amount_mismatch",
    "paid_reference_mismatch": "reference_mismatch",
    "binance_paid_manual_mode": "manual_mode",
}

# history `source` → public label
_SOURCE_LABELS = {
    "order_created": "order",
    "user_submit": "user",
    "user_check": "binance",
    "binance_webhook": "binance",
    "admin_reverify": "admin",
    "admin_approve": "admin",
    "admin_reject": "admin",
    "sweep": "system",
}

# history `to` → public step
_STEP_LABELS = {
    "awaiting_payment": "created",
    "under_review": "under_review",
    "verified": "verified",
    "rejected": "rejected",
    "expired": "expired",
    "failed": "failed",
    "completed": "completed",
}


def review_code(order_status: str | None, payment: dict) -> str | None:
    """
    Public reason an order sits in manual review; None when it is not in review.
    A user-submitted hash / screenshot has no internal reason → "user_submitted".
    """
    if order_status not in ("under_review", "payment_submitted"):
        return None
    reason = payment.get("review_reason")
    if not reason:
        return "user_submitted"
    if str(reason).startswith("paid_but_order_"):
        return "late_payment"
    return _REVIEW_CODES.get(str(reason), "other")


def timeline(history: list[dict] | None, limit: int = 20) -> list[dict[str, Any]]:
    """Oldest → newest, user-safe: {at, step, source}. Notes and actor names are dropped."""
    out: list[dict[str, Any]] = []
    for e in history or []:
        at = e.get("at")
        if not isinstance(at, datetime):
            continue
        out.append({
            "at": at,
            "step": _STEP_LABELS.get(str(e.get("to")), "other"),
            "source": _SOURCE_LABELS.get(str(e.get("source")), "system"),
        })
    out.sort(key=lambda x: x["at"])
    return out[-limit:]


def retry_info(effective_status: str, recent_failed: int, limit: int, has_access: bool) -> dict[str, Any]:
    """
    {"allowed": bool, "remaining": int | None}. `remaining` is None when the admin
    set no cap (limit = 0). Only an expired / failed order can be retried, and
    never when the user already has access.
    """
    if effective_status not in ("expired", "failed") or has_access:
        return {"allowed": False, "remaining": None}
    if limit <= 0:
        return {"allowed": True, "remaining": None}
    left = max(0, limit - recent_failed)
    return {"allowed": left > 0, "remaining": left}
