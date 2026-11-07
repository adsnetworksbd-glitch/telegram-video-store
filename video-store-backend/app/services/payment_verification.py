"""
Payment verification (Phase 10 — Part 2A).

One place for everything that decides "was this order really paid?":

* status history       — every payment state change is appended to
                         `payments/{id}.status_history` (no new collection)
* tx-hash claims       — a transaction hash can back ONE order, ever
* Binance Pay verify   — the ONLY automatic verifier. It asks Binance's signed
                         order-query API; neither the browser, a screenshot nor
                         the webhook body is ever trusted as proof.
* manual review        — anything not provable by API (wallet / Pay ID / custom
                         methods, amount mismatches, rejected-then-paid orders)
                         waits in `under_review` for an admin.

The decision itself (`decide_binance_outcome`) is a pure function so it can be
tested offline; the Firestore code around it is thin. Google / Binance imports
are done lazily so the pure parts stay importable without those packages.

Access is granted ONLY through `fulfill_order` (idempotent: deterministic
entitlement id), and only from the `fulfill` outcome or an admin approval.
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.webhook_utils import amount_covers

logger = logging.getLogger(__name__)

# ─── Admin-tunable defaults (Firestore app_settings/config wins; these only apply
#     when the key is absent). Keys: payment_verify_min_interval_seconds,
#     payment_retry_limit_24h.
DEFAULT_VERIFY_MIN_INTERVAL_S = 5
DEFAULT_RETRY_LIMIT_24H = 5

# verification_method values stored on the payment document
VERIFY_AUTO = "binance_webhook"    # name kept from Part 1 (frontend already maps it)
VERIFY_MANUAL = "manual"

# Binance order statuses
_BINANCE_PENDING = {"INITIAL", "PENDING"}
_BINANCE_DEAD = {"CANCELED", "EXPIRED"}

# Order states in which a Binance "PAID" may auto-grant access
_AUTO_FULFILLABLE = {"awaiting_payment", "pending", "expired", "payment_submitted", "under_review"}


# ─── Pure helpers ─────────────────────────────────────────────────────────────
def history_event(from_state: str | None, to_state: str, by: str, source: str,
                  note: str | None = None, now: datetime | None = None) -> dict:
    """One status-change record. `by` = user id / admin name / 'system'."""
    return {
        "at": now or datetime.now(timezone.utc),
        "from": from_state,
        "to": to_state,
        "by": by,
        "source": source,
        "note": (note or None) and str(note)[:300],
    }


def txhash_claim_id(normalized_hash: str) -> str:
    return "txclaim_" + hashlib.sha256(normalized_hash.encode()).hexdigest()[:40]


def verify_wait_seconds(payment: dict, now: datetime, min_interval_s: int) -> int:
    """Seconds the caller must still wait before another Binance query (0 = go)."""
    last = payment.get("last_checked_at")
    if last is None or min_interval_s <= 0:
        return 0
    left = min_interval_s - (now - last).total_seconds()
    return int(math.ceil(left)) if left > 0 else 0


def retry_limit_reached(recent_failed_or_expired: int, limit: int) -> bool:
    return limit > 0 and recent_failed_or_expired >= limit


@dataclass(frozen=True)
class Outcome:
    action: str                 # fulfill | review | fail | wait | noop
    reason: str
    paid_usdt: float | None = None
    order_status: str | None = None   # for action == "fail": expired | failed


def decide_binance_outcome(order: dict, payment: dict, binance: dict) -> Outcome:
    """
    Pure decision from (our order, our payment, Binance's order-query answer).

    Auto access requires ALL of: Binance status PAID; currency USDT; amount that
    covers what the backend asked for; the answer really being about THIS order
    (merchantTradeNo / prepayId); the method being in auto mode; and the order
    not having been rejected by an admin. Anything else that looks paid goes to
    manual review — never to access.
    """
    st = order.get("status")
    if st == "completed":
        return Outcome("noop", "already_completed")
    if st == "refunded":
        return Outcome("noop", "order_refunded")

    bstatus = str(binance.get("status") or "").upper()

    if bstatus in _BINANCE_PENDING or not bstatus:
        return Outcome("wait", "binance_" + (bstatus.lower() or "unknown"))

    if bstatus in _BINANCE_DEAD:
        if st in ("awaiting_payment", "pending", "expired"):
            return Outcome("fail", "binance_" + bstatus.lower(),
                           order_status="expired" if bstatus == "EXPIRED" else "failed")
        return Outcome("noop", "binance_closed_order_in_review")   # user/admin proof in flight

    if bstatus != "PAID":
        # REFUNDING / REFUNDED / ERROR / anything new: never grant, never reject by guess.
        return Outcome("wait", "binance_status_" + bstatus.lower())

    # ── PAID ──────────────────────────────────────────────────────────────────
    try:
        paid = float(binance.get("orderAmount"))
    except (TypeError, ValueError):
        return Outcome("review", "paid_amount_unreadable")

    mtn = binance.get("merchantTradeNo")
    prepay = binance.get("prepayId")
    expected_prepay = payment.get("binance_prepay_id")
    if (mtn and str(mtn) != str(order.get("_id"))) or (prepay and expected_prepay and str(prepay) != str(expected_prepay)):
        return Outcome("review", "paid_reference_mismatch", paid_usdt=paid)

    currency = str(binance.get("currency") or "").upper()
    expected = float(order.get("final_usdt") or 0)
    if currency != "USDT" or expected <= 0 or not amount_covers(expected, paid):
        return Outcome("review", "paid_amount_or_currency_mismatch", paid_usdt=paid)

    if payment.get("verification_method") != VERIFY_AUTO:
        return Outcome("review", "binance_paid_manual_mode", paid_usdt=paid)
    if st not in _AUTO_FULFILLABLE:
        return Outcome("review", "paid_but_order_" + str(st), paid_usdt=paid)
    return Outcome("fulfill", "binance_paid", paid_usdt=paid)


# ─── Firestore-bound helpers ──────────────────────────────────────────────────
async def payment_settings(db) -> dict:
    """Admin-controlled limits from app_settings/config (fallback to the defaults above)."""
    from app.db.firebase import Col
    snap = await db.collection(Col.APP_SETTINGS).document("config").get()
    cfg = (snap.to_dict() or {}) if snap.exists else {}

    def _int(key: str, default: int) -> int:
        try:
            return max(0, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "verify_min_interval_s": _int("payment_verify_min_interval_seconds", DEFAULT_VERIFY_MIN_INTERVAL_S),
        "retry_limit_24h": _int("payment_retry_limit_24h", DEFAULT_RETRY_LIMIT_24H),
    }


async def append_history(payment_ref, event: dict) -> None:
    """Append one event to the payment's status history (best effort — never blocks a payment)."""
    from google.cloud.firestore_v1 import ArrayUnion
    try:
        await payment_ref.update({"status_history": ArrayUnion([event]), "updated_at": event["at"]})
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Payment history append failed: {exc}")


async def claim_txhash(db, normalized_hash: str, *, payment_id: str, order_id: str, user_id: str) -> bool:
    """
    Atomically reserve a transaction hash for ONE order (document create() fails
    if it exists, so two simultaneous submissions cannot both win). Returns True
    when this order owns the claim (also for an idempotent repeat of the same
    submission), False when another order already used the hash.
    A rejected order keeps its claim on purpose: a refused hash must not be reusable.
    """
    from google.api_core.exceptions import AlreadyExists
    from app.db.firebase import Col

    ref = db.collection(Col.PAYMENTS).document(txhash_claim_id(normalized_hash))
    try:
        await ref.create({
            "kind": "txhash_claim",
            "txhash": normalized_hash,
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc),
        })
        return True
    except AlreadyExists:
        snap = await ref.get()
        existing = snap.to_dict() or {}
        return existing.get("order_id") == order_id and existing.get("user_id") == user_id


async def _load(db, order_id: str):
    from google.cloud.firestore_v1.base_query import FieldFilter
    from app.db.firebase import Col

    order_snap = await db.collection(Col.ORDERS).document(order_id).get()
    if not order_snap.exists:
        return None, None
    pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", order_id)).limit(1)
    pdocs = [d async for d in pq.stream()]
    return order_snap, (pdocs[0] if pdocs else None)


async def verify_binance_order(db, order_id: str, *, source: str, actor: str = "system") -> dict:
    """
    Verify a Binance Pay order against Binance's own API and act on the result.
    Idempotent and safe to call from the webhook, the user's "check payment"
    button and an admin re-verify at the same time.

    Raises binance.BinanceUnavailable when Binance cannot be asked — the order is
    left exactly as it was (never treated as unpaid, never as paid).
    Returns {"outcome", "reason", "order_status", "entitlement_id"}.
    """
    from google.cloud.firestore_v1 import Increment
    from google.cloud.firestore_v1.async_transaction import async_transactional
    from app.db.firebase import Col
    from app.services import binance
    from app.services.fulfillment import fulfill_order
    from app.services.payment_methods import is_gateway
    from app.utils.audit import audit_log

    order_snap, pay_snap = await _load(db, order_id)
    if order_snap is None or pay_snap is None:
        return {"outcome": "not_found", "reason": "order_or_payment_missing", "order_status": None, "entitlement_id": None}
    order = {**(order_snap.to_dict() or {}), "_id": order_id}
    payment = pay_snap.to_dict() or {}
    if not is_gateway(payment.get("payment_method", "")):
        return {"outcome": "not_gateway", "reason": "manual_method", "order_status": order.get("status"), "entitlement_id": None}
    if order.get("status") == "completed":
        return {"outcome": "noop", "reason": "already_completed", "order_status": "completed",
                "entitlement_id": order.get("entitlement_id")}

    binance_answer = await binance.query_order(order_id)      # may raise BinanceUnavailable
    now = datetime.now(timezone.utc)
    outcome = decide_binance_outcome(order, payment, binance_answer)
    order_ref = db.collection(Col.ORDERS).document(order_id)
    prev_state = order.get("status")

    base_update: dict[str, Any] = {
        "last_checked_at": now, "updated_at": now, "attempts": Increment(1),
        "binance_last_status": str(binance_answer.get("status") or "")[:32],
    }

    if outcome.action == "fulfill":
        @async_transactional
        async def _mark_verified(transaction):
            snap = await pay_snap.reference.get(transaction=transaction)
            if (snap.to_dict() or {}).get("verification_status") == "verified":
                return False
            transaction.update(pay_snap.reference, {
                **base_update,
                "binance_webhook_verified": True,   # name kept from Part 1: "Binance confirmed"
                "verification_status": "verified",
                "verified_by": actor,
                "verified_at": now,
                "paid_amount_usdt": outcome.paid_usdt,
            })
            return True

        first = await _mark_verified(db.transaction())
        # Always (re)run fulfilment: idempotent, and heals a crash after the mark.
        ent_id = await fulfill_order(db, order_id)
        if first:
            await append_history(pay_snap.reference, history_event(prev_state, "verified", actor, source, outcome.reason, now))
            await audit_log(
                action="binance_payment_verified", performed_by=actor, target_type="order", target_id=order_id,
                before={"status": prev_state},
                after={"source": source, "paid_usdt": outcome.paid_usdt, "entitlement_id": ent_id},
            )
        return {"outcome": "fulfilled", "reason": outcome.reason, "order_status": "completed", "entitlement_id": ent_id}

    if outcome.action == "review":
        review_update = {**base_update, "paid_amount_usdt": outcome.paid_usdt, "review_reason": outcome.reason}
        if payment.get("verification_status") == "failed":
            review_update["verification_status"] = "pending"   # money arrived after a rejection: back to an admin
        await pay_snap.reference.update(review_update)
        if prev_state != "under_review":
            await order_ref.update({"status": "under_review", "submitted_at": order.get("submitted_at") or now})
            await append_history(pay_snap.reference, history_event(prev_state, "under_review", actor, source, outcome.reason, now))
            await audit_log(
                action="binance_payment_needs_review", performed_by=actor, target_type="order", target_id=order_id,
                before={"status": prev_state},
                after={"reason": outcome.reason, "paid_usdt": outcome.paid_usdt,
                       "expected_usdt": order.get("final_usdt"), "source": source},
            )
        return {"outcome": "review", "reason": outcome.reason, "order_status": "under_review", "entitlement_id": None}

    if outcome.action == "fail":
        new_status = outcome.order_status or "failed"
        await pay_snap.reference.update({**base_update, "verification_status": "failed", "review_reason": outcome.reason})
        await order_ref.update({"status": new_status})
        await append_history(pay_snap.reference, history_event(prev_state, new_status, actor, source, outcome.reason, now))
        await audit_log(
            action="binance_payment_closed", performed_by=actor, target_type="order", target_id=order_id,
            before={"status": prev_state}, after={"status": new_status, "reason": outcome.reason, "source": source},
        )
        return {"outcome": "failed", "reason": outcome.reason, "order_status": new_status, "entitlement_id": None}

    # wait / noop: just remember that we asked
    await pay_snap.reference.update(base_update)
    return {"outcome": outcome.action, "reason": outcome.reason, "order_status": prev_state, "entitlement_id": None}
