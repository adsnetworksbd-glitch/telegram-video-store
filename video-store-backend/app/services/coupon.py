"""Coupon validation and usage recording."""
from datetime import datetime, timezone
import uuid
import logging

from google.cloud.firestore_v1 import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.db.firebase import Col
from app.schemas import CouponValidation

logger = logging.getLogger(__name__)


async def validate_coupon(
    db: AsyncClient,
    code: str,
    user_id: str,
    content_type: str,
    content_id: str,
    order_amount_bdt: float,
    pending_uses: int = 0,
) -> CouponValidation:
    """
    Validate coupon and return discount info.
    Does NOT record usage — that happens at order completion.
    `pending_uses` = how many of this user's other open (unpaid / in-review) orders
    already carry this coupon; they count against the per-user limit so one
    single-use coupon cannot be attached to several orders at the same time.
    """
    code_upper = code.strip().upper()
    now = datetime.now(timezone.utc)

    # Find coupon
    query = (
        db.collection(Col.COUPONS)
        .where(filter=FieldFilter("code", "==", code_upper))
        .where(filter=FieldFilter("is_active", "==", True))
        .limit(1)
    )
    docs = [d async for d in query.stream()]
    if not docs:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="Coupon কোড সঠিক নয়।")

    c = docs[0].to_dict() or {}
    coupon_id = docs[0].id

    # Validity period
    valid_from = c.get("valid_from")
    valid_until = c.get("valid_until")
    if valid_from and now < valid_from:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="Coupon এখনো শুরু হয়নি।")
    if valid_until and now > valid_until:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="Coupon-এর মেয়াদ শেষ।")

    # Usage limit
    usage_limit = c.get("usage_limit")
    used_count = c.get("used_count", 0)
    if usage_limit is not None and used_count >= usage_limit:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="Coupon ব্যবহারের সীমা শেষ।")

    # Per-user limit
    per_user_limit = c.get("per_user_limit", 1)
    usage_query = (
        db.collection(Col.COUPON_USAGE)
        .where(filter=FieldFilter("coupon_id", "==", coupon_id))
        .where(filter=FieldFilter("user_id", "==", user_id))
    )
    user_usages = [d async for d in usage_query.stream()]
    if len(user_usages) + max(0, pending_uses) >= per_user_limit:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="আপনি এই Coupon আগেই ব্যবহার করেছেন।")

    # Applicable content check
    applicable_to = c.get("applicable_to", "all")
    applicable_ids = c.get("applicable_ids", [])
    if applicable_to == "videos" and content_type == "video" and applicable_ids and content_id not in applicable_ids:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="এই ভিডিওতে Coupon প্রযোজ্য নয়।")
    if applicable_to == "packages" and content_type == "package" and applicable_ids and content_id not in applicable_ids:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message="এই প্যাকেজে Coupon প্রযোজ্য নয়।")

    # Minimum order
    min_order = c.get("min_order_bdt", 0)
    if order_amount_bdt < min_order:
        return CouponValidation(valid=False, discount_bdt=0, final_bdt=order_amount_bdt, message=f"ন্যূনতম অর্ডার ৳{min_order} হতে হবে।")

    # Calculate discount
    discount_type = c.get("discount_type", "fixed_bdt")
    discount_value = c.get("discount_value", 0)
    max_discount = c.get("max_discount_bdt")

    if discount_type == "percentage":
        discount = round(order_amount_bdt * discount_value / 100, 2)
        if max_discount:
            discount = min(discount, max_discount)
    else:
        discount = min(discount_value, order_amount_bdt)

    final = max(0, round(order_amount_bdt - discount, 2))
    return CouponValidation(
        valid=True,
        discount_bdt=discount,
        final_bdt=final,
        message=f"✅ {discount_value}{'%' if discount_type == 'percentage' else ' টাকা'} ছাড় প্রযোজ্য!",
    )


async def record_coupon_usage(
    db: AsyncClient,
    coupon_code: str,
    user_id: str,
    order_id: str,
    discount_bdt: float,
) -> None:
    """Record coupon usage atomically after order completion."""
    code_upper = coupon_code.strip().upper()

    # Find coupon
    query = (
        db.collection(Col.COUPONS)
        .where(filter=FieldFilter("code", "==", code_upper))
        .limit(1)
    )
    docs = [d async for d in query.stream()]
    if not docs:
        return

    coupon_ref = docs[0].reference
    coupon_data = docs[0].to_dict() or {}

    # Idempotency: check if already recorded for this order
    existing = (
        db.collection(Col.COUPON_USAGE)
        .where(filter=FieldFilter("order_id", "==", order_id))
        .limit(1)
    )
    if [d async for d in existing.stream()]:
        return  # Already recorded

    usage_id = f"{docs[0].id}_{user_id}_{order_id}"
    await db.collection(Col.COUPON_USAGE).document(usage_id).set({
        "coupon_id": docs[0].id,
        "user_id": user_id,
        "order_id": order_id,
        "discount_applied_bdt": discount_bdt,
        "used_at": datetime.now(timezone.utc),
    })

    # Increment used_count
    current = coupon_data.get("used_count", 0)
    await coupon_ref.update({"used_count": current + 1})
