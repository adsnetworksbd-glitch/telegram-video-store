"""Referral system — fraud-protected, coupon-based reward."""
from datetime import datetime, timezone, timedelta
import uuid
import logging

from google.cloud.firestore_v1 import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.db.firebase import Col
from app.utils.audit import create_notification

logger = logging.getLogger(__name__)


async def process_referral_on_register(
    db: AsyncClient,
    referred_user_id: str,
    referral_code: str,
) -> None:
    """
    Called when a new user registers with a referral code.
    Creates a pending referral record.
    Does NOT reward yet — reward happens after qualifying purchase.
    """
    # Find referrer by referral_code
    query = (
        db.collection(Col.USERS)
        .where(filter=FieldFilter("referral_code", "==", referral_code))
        .limit(1)
    )
    docs = [d async for d in query.stream()]
    if not docs:
        logger.warning(f"Referral code not found: {referral_code}")
        return

    referrer_id = docs[0].id
    if referrer_id == referred_user_id:
        return  # Self-referral prevention

    # Check no duplicate referral exists
    existing_q = (
        db.collection(Col.REFERRALS)
        .where(filter=FieldFilter("referred_user_id", "==", referred_user_id))
        .limit(1)
    )
    if [d async for d in existing_q.stream()]:
        return  # Already has a referral

    ref_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.collection(Col.REFERRALS).document(ref_id).set({
        "referrer_user_id": referrer_id,
        "referred_user_id": referred_user_id,
        "referral_code": referral_code,
        "status": "pending",
        "referred_account_age_hours": 0,
        "qualifying_order_id": None,
        "reward_type": None,
        "reward_amount_bdt": None,
        "reward_coupon_id": None,
        "rewarded_at": None,
        "reward_transaction_id": None,
        "created_at": now,
    })
    logger.info(f"Referral {ref_id} created: {referrer_id} → {referred_user_id}")


async def process_referral_on_purchase(
    db: AsyncClient,
    referred_user_id: str,
    order_id: str,
) -> None:
    """
    Called after a purchase is completed.
    Rewards referrer if conditions met and fraud check passes.
    """
    # Get app settings for referral config
    cfg_doc = await db.collection(Col.APP_SETTINGS).document("config").get()
    cfg = cfg_doc.to_dict() or {} if cfg_doc.exists else {}

    if not cfg.get("referral_enabled", False):
        return

    fraud_cooldown_hours = cfg.get("referral_fraud_cooldown_hours", 48)
    min_purchase_required = cfg.get("referral_min_purchase_required", True)
    reward_type = cfg.get("referral_reward_type", "coupon")
    reward_amount = cfg.get("referral_reward_amount", 100)
    coupon_valid_days = cfg.get("referral_coupon_valid_days", 7)   # admin setting; 7 = the previous fixed value

    # Find pending referral for this user
    query = (
        db.collection(Col.REFERRALS)
        .where(filter=FieldFilter("referred_user_id", "==", referred_user_id))
        .where(filter=FieldFilter("status", "==", "pending"))
        .limit(1)
    )
    docs = [d async for d in query.stream()]
    if not docs:
        return

    ref_doc = docs[0]
    ref_data = ref_doc.to_dict() or {}
    referrer_id = ref_data["referrer_user_id"]

    # Fraud check: account age
    referred_user_doc = await db.collection(Col.USERS).document(referred_user_id).get()
    referred_user = referred_user_doc.to_dict() or {}
    created_at = referred_user.get("created_at")
    if created_at:
        account_age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
        if account_age_hours < fraud_cooldown_hours:
            logger.warning(f"Referral fraud check failed: account too new ({account_age_hours:.1f}h < {fraud_cooldown_hours}h)")
            await ref_doc.reference.update({"status": "fraud_detected"})
            return

    # Update referral to qualifying
    await ref_doc.reference.update({
        "status": "qualifying",
        "qualifying_order_id": order_id,
        "referred_account_age_hours": account_age_hours if created_at else 0,
    })

    # Issue reward
    reward_coupon_id = None
    if reward_type == "coupon":
        reward_coupon_id = await _create_referral_coupon(db, referrer_id, reward_amount, coupon_valid_days)

    await ref_doc.reference.update({
        "status": "rewarded",
        "reward_type": reward_type,
        "reward_amount_bdt": reward_amount if reward_type != "coupon" else None,
        "reward_coupon_id": reward_coupon_id,
        "rewarded_at": datetime.now(timezone.utc),
    })

    # Increment referrer's referral_count and total reward
    referrer_ref = db.collection(Col.USERS).document(referrer_id)
    referrer_doc = await referrer_ref.get()
    if referrer_doc.exists:
        referrer_data = referrer_doc.to_dict() or {}
        await referrer_ref.update({
            "referral_count": referrer_data.get("referral_count", 0) + 1,
            "referral_reward_total_bdt": referrer_data.get("referral_reward_total_bdt", 0) + reward_amount,
        })

    # Notify referrer
    await create_notification(
        user_id=referrer_id,
        type_="referral_reward",
        title="🎁 Referral Reward পেয়েছেন!",
        body=f"আপনার Referral একটি purchase করেছে। আপনি {'একটি Coupon' if reward_type == 'coupon' else f'৳{reward_amount}'} Reward পেয়েছেন।",
    )

    logger.info(f"Referral rewarded: {referrer_id} ← {referred_user_id}")


async def _create_referral_coupon(
    db: AsyncClient,
    user_id: str,
    discount_bdt: float,
    valid_days: int = 7,
) -> str:
    """Create a one-time use coupon for referral reward."""
    import random
    import string
    code = "REF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    coupon_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.collection(Col.COUPONS).document(coupon_id).set({
        "code": code,
        "discount_type": "fixed_bdt",
        "discount_value": discount_bdt,
        "max_discount_bdt": None,
        "applicable_to": "all",
        "applicable_ids": [],
        "min_order_bdt": 0,
        "usage_limit": 1,
        "used_count": 0,
        "per_user_limit": 1,
        "is_active": True,
        "valid_from": now,
        "valid_until": now + timedelta(days=valid_days if isinstance(valid_days, int) and not isinstance(valid_days, bool) and valid_days > 0 else 7),
        "created_at": now,
        "created_for_user": user_id,
        "type": "referral_reward",
    })
    return coupon_id
