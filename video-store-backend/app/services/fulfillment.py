"""
Order fulfillment — called ONLY after a payment is verified (Binance API
confirmation or an admin approval).

Creates the entitlement (access), records the ledger entry (purchase record),
completes the order and triggers the referral reward.

Idempotent AND crash-safe (Phase 10 Part 2B): every step can be re-run.
  1. entitlement  — deterministic id `ent_<order_id>` (create-once)
  2. ledger entry — deterministic id `txn_purchase_<order_id>` (create-once)
  3. order → completed — a Firestore transaction; exactly ONE caller wins it
  4. counters / coupon / referral — only the winner of step 3 runs them

If a previous run died after step 1 or 2, the next run (webhook retry, user
"check payment", admin approve/re-verify) simply continues from there instead
of returning early and leaving the order un-completed.
"""
from datetime import datetime, timezone
import logging

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1 import AsyncClient
from google.cloud.firestore_v1.async_transaction import async_transactional

from app.db.firebase import Col
from app.services.entitlement import create_entitlement
from app.services.transaction import record_transaction
from app.services.coupon import record_coupon_usage
from app.services.referral import process_referral_on_purchase
from app.utils.audit import audit_log

logger = logging.getLogger(__name__)

# Only these order states may be turned into "completed". `failed` (rejected /
# closed) and `refunded` never grant access; a rejected order that is paid later
# is first sent back to `under_review` by the verifier and needs an admin.
FULFILLABLE_STATUSES = frozenset({
    "awaiting_payment", "pending", "expired", "payment_submitted", "under_review",
})


def ledger_tx_id(order_id: str) -> str:
    return f"txn_purchase_{order_id}"


async def fulfill_order(db: AsyncClient, order_id: str) -> str | None:
    """
    Returns the entitlement id, or None when the order must NOT be fulfilled
    (missing, refunded, failed/rejected, ...). Safe to call any number of times,
    also concurrently.
    """
    order_ref = db.collection(Col.ORDERS).document(order_id)
    order_doc = await order_ref.get()
    if not order_doc.exists:
        logger.error(f"Order {order_id} not found for fulfillment")
        return None

    order = order_doc.to_dict() or {}
    status = order.get("status")

    # Idempotency: already completed
    if status == "completed":
        logger.info(f"Order {order_id} already fulfilled")
        return order.get("entitlement_id")

    if status not in FULFILLABLE_STATUSES:
        logger.warning(f"Order {order_id} is '{status}' — not fulfilling")
        return None

    user_id       = order["user_id"]
    content_type  = order["content_type"]
    content_id    = order["content_id"]
    final_bdt     = order.get("final_bdt", 0)

    # Load content to get the access-duration rule (0 hours = lifetime)
    if content_type == "video":
        content_doc = await db.collection(Col.VIDEOS).document(content_id).get()
        content = content_doc.to_dict() or {}
        duration_hours = content.get("purchase_duration_hours", 0)
        included_ids   = []
    else:
        content_doc = await db.collection(Col.PACKAGES).document(content_id).get()
        content = content_doc.to_dict() or {}
        duration_type  = content.get("duration_type", "lifetime")
        duration_hours = 0 if duration_type == "lifetime" else content.get("duration_hours", 0)
        included_ids   = content.get("video_ids", [])

    # 1. Entitlement — deterministic id → exactly one per order. If it already
    #    exists (a crashed earlier run, or a racing caller) we CONTINUE with the
    #    remaining steps rather than stopping here.
    ent_id = f"ent_{order_id}"   # same deterministic id as below (kept as a literal for the static contract tests)
    try:
        ent_id = await create_entitlement(
            db=db,
            user_id=user_id,
            content_type=content_type,
            content_id=content_id,
            access_source="individual_purchase" if content_type == "video" else "package_purchase",
            duration_hours=duration_hours,
            order_id=order_id,
            included_video_ids=included_ids,
            entitlement_id=f"ent_{order_id}",
        )
    except AlreadyExists:
        logger.info(f"Order {order_id}: entitlement already exists — resuming fulfilment")

    # 2. Purchase record (ledger) — create-once
    await record_transaction(
        db=db,
        user_id=user_id,
        type_="purchase",
        amount_bdt=final_bdt,
        direction="debit",
        reference_type="order",
        reference_id=order_id,
        description=f"{'ভিডিও' if content_type == 'video' else 'প্যাকেজ'} Purchase",
        tx_id=ledger_tx_id(order_id),
    )

    # 3. Complete the order — only ONE caller wins this transition
    @async_transactional
    async def _complete(transaction) -> bool:
        snap = await order_ref.get(transaction=transaction)
        cur = snap.to_dict() or {}
        if cur.get("status") not in FULFILLABLE_STATUSES:
            return False        # already completed by someone else (or no longer payable)
        transaction.update(order_ref, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "entitlement_id": ent_id,
        })
        return True

    won = await _complete(db.transaction())
    if not won:
        logger.info(f"Order {order_id}: completion handled by another caller")
        return ent_id

    # 4. Winner-only side effects (never repeated for the same order)
    col = Col.VIDEOS if content_type == "video" else Col.PACKAGES
    try:
        content_ref = db.collection(col).document(content_id)
        c_doc = await content_ref.get()
        if c_doc.exists:
            current_count = (c_doc.to_dict() or {}).get("purchase_count", 0)
            await content_ref.update({"purchase_count": current_count + 1})
    except Exception as e:  # noqa: BLE001 — access is already granted; counters are best effort
        logger.error(f"purchase_count update failed for order {order_id}: {e}")

    if order.get("coupon_code"):
        try:
            await record_coupon_usage(
                db, order["coupon_code"], user_id, order_id, order.get("discount_bdt", 0.0)
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Coupon usage record failed for order {order_id}: {e}")

    try:
        await process_referral_on_purchase(db, user_id, order_id)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Referral processing failed for order {order_id}: {e}")

    await audit_log(
        action="order_fulfilled",
        performed_by="system",
        target_type="order",
        target_id=order_id,
        after={"entitlement_id": ent_id, "user_id": user_id},
    )

    logger.info(f"Order {order_id} fulfilled → entitlement {ent_id}")
    return ent_id
