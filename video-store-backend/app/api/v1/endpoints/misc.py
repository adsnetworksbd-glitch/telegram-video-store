"""Coupons, Referral, User, Search, Support, Binance webhook."""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.firebase import get_db, Col
from app.schemas import (
    CouponValidateRequest, CouponValidation,
    ReferralInfo, ReferralListResponse, Referral,
    Transaction, TransactionListResponse,
    Notification, NotificationListResponse, MarkReadRequest,
    FAQ, FAQListResponse, SupportTicketRequest, SupportTicketResponse,
    SearchResponse,
    UserProfile,
)
from app.services.coupon import validate_coupon
from app.services.fulfillment import fulfill_order
from app.services.binance import verify_binance_webhook
from app.utils.audit import audit_log, create_notification
from app.api.v1.endpoints.videos import _safe_video
from app.api.v1.endpoints.packages import _safe_package

router = APIRouter(tags=["misc"])


# ─── Coupons ──────────────────────────────────────────────────────────────────
@router.post("/coupons/validate", response_model=CouponValidation)
async def validate_coupon_endpoint(
    body: CouponValidateRequest,
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    return await validate_coupon(
        db, body.code, user_id,
        body.content_type, body.content_id, body.order_amount_bdt,
    )


# ─── Referral ─────────────────────────────────────────────────────────────────
@router.get("/referral/info", response_model=ReferralInfo)
async def referral_info(user_id: str = Depends(get_current_user)):
    db = get_db()
    doc = await db.collection(Col.USERS).document(user_id).get()
    data = doc.to_dict() or {}
    code = data.get("referral_code", "")
    cfg_doc = await db.collection(Col.APP_SETTINGS).document("config").get()
    cfg = cfg_doc.to_dict() if cfg_doc.exists else {}
    bot_username = cfg.get("telegram_bot_username") or settings.TELEGRAM_BOT_USERNAME
    return ReferralInfo(
        referral_code=code,
        referral_count=data.get("referral_count", 0),
        reward_total_bdt=data.get("referral_reward_total_bdt", 0.0),
        referral_link=f"https://t.me/{bot_username}?start={code}",
    )


@router.get("/referral/history", response_model=ReferralListResponse)
async def referral_history(
    user_id: str = Depends(get_current_user),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    q = (
        db.collection(Col.REFERRALS)
        .where(filter=FieldFilter("referrer_user_id", "==", user_id))
        .order_by("created_at", direction="DESCENDING")
    )
    all_docs = [d async for d in q.stream()]
    total = len(all_docs)
    start = (page - 1) * limit
    items = []
    for d in all_docs[start:start + limit]:
        data = d.to_dict() or {}
        items.append(Referral(
            id=d.id,
            referred_user_id=data.get("referred_user_id", ""),
            status=data.get("status", "pending"),
            reward_type=data.get("reward_type", "coupon"),
            reward_amount_bdt=data.get("reward_amount_bdt"),
            created_at=data["created_at"],
        ))
    return ReferralListResponse(items=items, total=total, page=page, has_more=start + limit < total)


# ─── User ─────────────────────────────────────────────────────────────────────
@router.get("/user/profile", response_model=UserProfile)
async def user_profile(user_id: str = Depends(get_current_user)):
    db = get_db()
    doc = await db.collection(Col.USERS).document(user_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    data = doc.to_dict() or {}
    return UserProfile(
        telegram_id=user_id,
        username=data.get("username"),
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name"),
        photo_url=data.get("photo_url"),
        referral_code=data.get("referral_code", ""),
        referral_count=data.get("referral_count", 0),
        referral_reward_total_bdt=data.get("referral_reward_total_bdt", 0.0),
        total_spent_bdt=data.get("total_spent_bdt", 0.0),
        wallet_balance=0.0,
        wallet_enabled=False,
        is_banned=data.get("is_banned", False),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
        last_seen_at=data.get("last_seen_at", datetime.now(timezone.utc)),
    )


@router.get("/user/transactions", response_model=TransactionListResponse)
async def user_transactions(
    user_id: str = Depends(get_current_user),
    type: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    q = (
        db.collection(Col.TRANSACTIONS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("created_at", direction="DESCENDING")
    )
    if type:
        q = q.where(filter=FieldFilter("type", "==", type))
    all_docs = [d async for d in q.stream()]
    total = len(all_docs)
    start = (page - 1) * limit
    items = []
    for d in all_docs[start:start + limit]:
        data = d.to_dict() or {}
        items.append(Transaction(
            id=d.id, type=data.get("type", ""),
            amount_bdt=data.get("amount_bdt", 0),
            direction=data.get("direction", "debit"),
            reference_type=data.get("reference_type", ""),
            reference_id=data.get("reference_id", ""),
            description=data.get("description", ""),
            created_at=data["created_at"],
        ))
    return TransactionListResponse(items=items, total=total, page=page, has_more=start + limit < total)


@router.get("/user/notifications", response_model=NotificationListResponse)
async def user_notifications(
    user_id: str = Depends(get_current_user),
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
):
    db = get_db()
    q = (
        db.collection(Col.NOTIFICATIONS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("created_at", direction="DESCENDING")
    )
    if unread_only:
        q = q.where(filter=FieldFilter("is_read", "==", False))
    all_docs = [d async for d in q.stream()]
    total = len(all_docs)
    start = (page - 1) * limit
    items = []
    for d in all_docs[start:start + limit]:
        data = d.to_dict() or {}
        items.append(Notification(
            id=d.id, type=data.get("type", ""),
            title=data.get("title", ""), body=data.get("body", ""),
            is_read=data.get("is_read", False),
            action_type=data.get("action_type"),
            action_id=data.get("action_id"),
            created_at=data["created_at"],
        ))
    unread_count = sum(1 for d in all_docs if not (d.to_dict() or {}).get("is_read"))
    return NotificationListResponse(notifications=items, unread_count=unread_count)


@router.post("/user/notifications/read", response_model=dict)
async def mark_notifications_read(
    body: MarkReadRequest,
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    q = db.collection(Col.NOTIFICATIONS).where(filter=FieldFilter("user_id", "==", user_id))
    if body.notification_ids != "all":
        docs = []
        for nid in body.notification_ids:
            d = await db.collection(Col.NOTIFICATIONS).document(nid).get()
            if d.exists and (d.to_dict() or {}).get("user_id") == user_id:
                docs.append(d)
    else:
        docs = [d async for d in q.where(filter=FieldFilter("is_read", "==", False)).stream()]

    count = 0
    for d in docs:
        await d.reference.update({"is_read": True})
        count += 1
    return {"updated": count}


# ─── Search ───────────────────────────────────────────────────────────────────
@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    type: str = Query("all"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    """
    Simple title-based search (Firestore doesn't support full-text).
    For production: integrate Algolia or Typesense.
    """
    db = get_db()
    term = q.lower()
    videos = []
    packages = []

    if type in ("all", "videos"):
        video_docs = [d async for d in db.collection(Col.VIDEOS)
                      .where(filter=FieldFilter("is_published", "==", True))
                      .order_by("created_at", direction="DESCENDING")
                      .limit(200)
                      .stream()]
        for d in video_docs:
            data = d.to_dict() or {}
            if term in data.get("title", "").lower():
                v = _safe_video(d.id, data)
                if v is not None:
                    videos.append(v)

    if type in ("all", "packages"):
        pkg_docs = [d async for d in db.collection(Col.PACKAGES)
                    .where(filter=FieldFilter("is_published", "==", True))
                    .order_by("created_at", direction="DESCENDING")
                    .limit(100)
                    .stream()]
        for d in pkg_docs:
            data = d.to_dict() or {}
            if term in data.get("name", "").lower():
                pk = _safe_package(d.id, data)
                if pk is not None:
                    packages.append(pk)

    return SearchResponse(videos=videos[:limit], packages=packages[:limit], total=len(videos) + len(packages))


# ─── Support ──────────────────────────────────────────────────────────────────
@router.get("/support/faq", response_model=FAQListResponse)
async def get_faq():
    db = get_db()
    q = db.collection(Col.FAQ).where(filter=FieldFilter("is_visible", "==", True)).order_by("display_order")
    docs = [d async for d in q.stream()]
    faqs = [FAQ(id=d.id, question=(d.to_dict() or {}).get("question", ""), answer=(d.to_dict() or {}).get("answer", "")) for d in docs]
    return FAQListResponse(faqs=faqs)


@router.post("/support/ticket", response_model=SupportTicketResponse)
async def create_ticket(
    body: SupportTicketRequest,
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    ticket_id = str(uuid.uuid4())
    await db.collection(Col.SUPPORT_TICKETS).document(ticket_id).set({
        "user_id": user_id,
        "subject": body.subject[:200],
        "message": body.message[:2000],
        "category": body.category,
        "status": "open",
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
        "admin_reply": None,
    })
    return SupportTicketResponse(ticket_id=ticket_id)


# ─── Binance Pay Webhook ──────────────────────────────────────────────────────
@router.post("/webhooks/binance-pay")
async def binance_pay_webhook(request: Request):
    """
    Binance Pay payment notification.

    The webhook is only a TRIGGER. Its signature is checked (Binance RSA
    certificate, or our HMAC secret) and then the order is verified again with
    Binance's signed order-query API — the notification body is never the proof
    of payment. Idempotent: safe to receive many times, in any order.
    """
    from app.services import binance as binance_api
    from app.services.payment_verification import verify_binance_order

    body_bytes = await request.body()
    try:
        body_str = body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid body")

    timestamp = request.headers.get("BinancePay-Timestamp", "")
    nonce = request.headers.get("BinancePay-Nonce", "")
    signature = request.headers.get("BinancePay-Signature", "")
    cert_sn = request.headers.get("BinancePay-Certificate-SN", "")

    # Fail CLOSED: with no secret configured every webhook is rejected, so an
    # unconfigured deployment can never be tricked into granting access.
    if not settings.BINANCE_PAY_API_SECRET or not signature:
        raise HTTPException(status_code=403, detail="Invalid Binance Pay signature")
    try:
        genuine = await binance_api.verify_webhook_signature(body_str, timestamp, nonce, signature, cert_sn)
    except binance_api.BinanceUnavailable:
        raise HTTPException(status_code=503, detail="Cannot verify webhook right now")   # Binance retries
    if not genuine:
        raise HTTPException(status_code=403, detail="Invalid Binance Pay signature")

    try:
        payload = json.loads(body_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("bizType") != "PAY":
        return {"returnCode": "SUCCESS", "returnMessage": "ignored"}

    try:
        raw = payload.get("data", "{}")
        biz_data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        if not isinstance(biz_data, dict):
            raise ValueError("not an object")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook data")
    merchant_trade_no = biz_data.get("merchantTradeNo")  # = order_id
    if not merchant_trade_no:
        return {"returnCode": "SUCCESS", "returnMessage": "no order id"}

    db = get_db()
    try:
        result = await verify_binance_order(db, str(merchant_trade_no), source="binance_webhook")
    except binance_api.BinanceUnavailable:
        # Could not confirm with Binance: do NOT acknowledge, so Binance retries.
        raise HTTPException(status_code=503, detail="Verification temporarily unavailable")
    return {"returnCode": "SUCCESS", "returnMessage": result["outcome"]}
