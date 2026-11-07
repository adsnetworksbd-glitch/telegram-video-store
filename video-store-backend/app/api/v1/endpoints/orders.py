"""Orders, Entitlements, Payment Methods endpoints."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud.firestore_v1.base_query import FieldFilter

import logging

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.firebase import get_db, Col
from app.schemas import (
    OrderCreateRequest, OrderCreateResponse, PaymentDetails,
    OrderDetailResponse, Order, Payment,
    PaymentSubmitRequest, PaymentSubmitResponse,
    PaymentVerifyResponse, OrderRetryRequest, TimelineEvent, RetryInfo,
    PaymentMethodListResponse, PaymentMethod,
    EntitlementListResponse, Entitlement,
    AccessStatus,
)
from app.services.entitlement import (
    has_any_access, check_video_access, check_package_access,
)
from app.services.maintenance import ensure_not_in_maintenance
from app.services.access_rules import entitlement_state
from app.services.coupon import validate_coupon, record_coupon_usage
from app.services.binance import create_prepay_order, BinanceUnavailable
from app.services.payment_methods import (
    normalize_method, is_payable, is_gateway, amount_problem, timeout_minutes,
    normalize_txhash, txhash_problem,
)
from app.services.payment_verification import (
    VERIFY_AUTO, VERIFY_MANUAL, history_event, append_history, claim_txhash,
    payment_settings, verify_wait_seconds, retry_limit_reached, verify_binance_order,
)
from app.services.order_view import review_code, timeline as public_timeline, retry_info
from app.utils.audit import audit_log, create_notification
from app.api.v1.endpoints.videos import _doc_to_video
from app.api.v1.endpoints.packages import _doc_to_package

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orders"])


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _effective_order_status(od: dict, now: datetime) -> str:
    """
    The backend has no scheduler, so an unpaid order never leaves
    `awaiting_payment` on its own. Derive `expired` when the payment window has
    passed. Only `awaiting_payment` is affected: a submitted/under-review order
    is waiting on an admin, not on the user's clock.
    """
    st = od.get("status", "pending")
    exp = od.get("expires_at")
    if st == "awaiting_payment" and exp is not None and exp < now:
        return "expired"
    return st


async def _join_entitlement_content(db, items: list[Entitlement]) -> None:
    """
    Attach `video` / `package` to each entitlement so My Purchases does not need
    one extra request per row. Read-only, de-duplicated, batched (get_all).
    Failure degrades to the old behaviour (fields stay None) — never a 500.
    """
    try:
        vid_ids = {e.content_id for e in items if e.content_type == "video"}
        pkg_ids = {e.content_id for e in items if e.content_type == "package"}
        videos, packages = {}, {}
        if vid_ids:
            refs = [db.collection(Col.VIDEOS).document(i) for i in vid_ids]
            async for snap in db.get_all(refs):
                if snap.exists:
                    videos[snap.id] = _doc_to_video(snap.id, snap.to_dict() or {})
        if pkg_ids:
            refs = [db.collection(Col.PACKAGES).document(i) for i in pkg_ids]
            async for snap in db.get_all(refs):
                if snap.exists:
                    packages[snap.id] = _doc_to_package(snap.id, snap.to_dict() or {})
        for e in items:
            if e.content_type == "video":
                e.video = videos.get(e.content_id)
            else:
                e.package = packages.get(e.content_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Entitlement content join skipped: {exc}")


# ─── Duplicate-order prevention (Phase 10) ────────────────────────────────────
# One open (awaiting_payment) order per user+content+method+coupon. A repeated
# tap / retry returns the SAME order instead of creating another one. The lock
# serialises concurrent requests of one user inside this process (Render runs a
# single web process); the Firestore query is the source of truth across restarts.
_ORDER_LOCKS: dict[str, asyncio.Lock] = {}


def _order_lock(uid: str, content_type: str, content_id: str) -> asyncio.Lock:
    key = f"{uid}:{content_type}:{content_id}"
    if len(_ORDER_LOCKS) > 2048:   # bounded: drop idle locks
        for k in [k for k, l in _ORDER_LOCKS.items() if not l.locked()]:
            _ORDER_LOCKS.pop(k, None)
    return _ORDER_LOCKS.setdefault(key, asyncio.Lock())


def _details_from_docs(payment_id: str, pd: dict, method: dict, expires_at: datetime,
                       *, reused: bool) -> PaymentDetails:
    """PaymentDetails from the stored payment snapshot (falls back to the method)."""
    gateway = is_gateway(method["type"])
    return PaymentDetails(
        payment_id=payment_id,
        method=pd.get("payment_method") or method["type"],
        expected_usdt=pd.get("expected_usdt", 0),
        wallet_address=None if gateway else (pd.get("wallet_address") or method["wallet_address"]),
        network=None if gateway else (pd.get("network") or method["network_name"]),
        qr_code_url=None if gateway else method["qr_code_url"],
        binance_checkout_url=pd.get("binance_checkout_url"),
        instructions_text=method["instructions_text"],
        expires_at=expires_at,
        method_name=method["name"],
        currency=method["currency"],
        pay_id=None if gateway else (pd.get("pay_id") or method["pay_id"]),
        merchant_name=method["merchant_name"],
        auto_verification_supported=method["auto_verification_supported"],
        manual_review_supported=method["manual_review_supported"],
        reused=reused,
    )


async def _expire_user_stale_orders(db, uid: str, now: datetime) -> None:
    """Persist `expired` for this user's own overdue unpaid orders (best effort)."""
    try:
        q = (
            db.collection(Col.ORDERS)
            .where(filter=FieldFilter("user_id", "==", uid))
            .where(filter=FieldFilter("status", "==", "awaiting_payment"))
        )
        async for d in q.stream():
            od = d.to_dict() or {}
            if od.get("expires_at") is not None and od["expires_at"] < now:
                await d.reference.update({"status": "expired"})
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Stale-order expiry skipped for {uid}: {exc}")


async def _coupon_pending_uses(db, uid: str, code: str, ctype: str, cid: str, now: datetime) -> int:
    """
    Open orders of this user (other content) that already hold this coupon: unpaid and
    not yet expired, or paid-and-waiting-for-review. The same content is excluded — an
    open order for it is reused or superseded by the duplicate-order logic below.
    """
    code_u = code.strip().upper()
    n = 0
    q = (
        db.collection(Col.ORDERS)
        .where(filter=FieldFilter("user_id", "==", uid))
        .where(filter=FieldFilter("status", "in", ["awaiting_payment", "payment_submitted", "under_review"]))
    )
    async for d in q.stream():
        od = d.to_dict() or {}
        if (od.get("coupon_code") or "").upper() != code_u:
            continue
        if od.get("content_type") == ctype and od.get("content_id") == cid:
            continue
        if od.get("status") == "awaiting_payment" and (od.get("expires_at") is None or od["expires_at"] <= now):
            continue
        n += 1
    return n


async def _recent_unpaid_count(db, uid: str, ctype: str, cid: str, now: datetime) -> int:
    """Expired/failed orders of this user for this item in the last 24h (retry-cap input)."""
    since = now - timedelta(hours=24)
    q = (
        db.collection(Col.ORDERS)
        .where(filter=FieldFilter("user_id", "==", uid))
        .where(filter=FieldFilter("created_at", ">=", since))
    )
    n = 0
    async for d in q.stream():
        od = d.to_dict() or {}
        if od.get("content_type") == ctype and od.get("content_id") == cid \
                and _effective_order_status(od, now) in ("expired", "failed"):
            n += 1
    return n


# ─── Payment Methods ──────────────────────────────────────────────────────────
@router.get("/payment-methods", response_model=PaymentMethodListResponse)
async def list_payment_methods():
    """
    Public method list for the checkout screen. Only enabled AND payable
    methods are returned; nothing secret is ever included (Binance API
    credentials live in the server environment, not in these documents).
    """
    db = get_db()
    q = (
        db.collection(Col.PAYMENT_METHODS)
        .where(filter=FieldFilter("is_enabled", "==", True))
        .order_by("display_order")
    )
    methods = []
    async for d in q.stream():
        m = normalize_method(d.id, d.to_dict() or {})
        if not is_payable(m):
            continue
        methods.append(PaymentMethod(**{k: m[k] for k in PaymentMethod.model_fields}))
    return PaymentMethodListResponse(methods=methods)


# ─── Entitlements ─────────────────────────────────────────────────────────────
@router.get("/entitlements", response_model=EntitlementListResponse)
async def list_entitlements(
    user_id: str = Depends(get_current_user),
    type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    query = db.collection(Col.ENTITLEMENTS).where(
        filter=FieldFilter("user_id", "==", user_id)
    )
    if type:
        query = query.where(filter=FieldFilter("content_type", "==", type))
    # NOTE: stored status is only ever 'active'/'revoked'; time-based expiry is
    # derived below, so `status` is filtered AFTER computing the effective value.
    query = query.order_by("created_at", direction="DESCENDING")
    now = datetime.now(timezone.utc)

    # Same rule as the access check (app.services.access_rules): a temporary
    # entitlement without a usable expiry is NOT shown as active.
    def _effective_status(data: dict) -> str:
        return entitlement_state(data, now)

    all_docs = []
    async for d in query.stream():
        data = d.to_dict() or {}
        eff = _effective_status(data)
        if status and eff != status:
            continue
        all_docs.append((d, data, eff))
    total = len(all_docs)
    start = (page - 1) * limit

    items = []
    for d, data, eff in all_docs[start:start + limit]:
        items.append(Entitlement(
            id=d.id,
            user_id=data["user_id"],
            content_type=data["content_type"],
            content_id=data["content_id"],
            included_video_ids=data.get("included_video_ids", []),
            access_source=data.get("access_source", "individual_purchase"),
            order_id=data.get("order_id"),
            ad_unlock_session_id=data.get("ad_unlock_session_id"),
            start_at=data["start_at"],
            expires_at=data.get("expires_at"),
            is_lifetime=data.get("is_lifetime", True),
            status=eff,
            created_at=data["created_at"],
        ))
    await _join_entitlement_content(db, items)
    return EntitlementListResponse(items=items, total=total, page=page, has_more=start + limit < total)


@router.get("/entitlements/check/video/{video_id}", response_model=AccessStatus)
async def check_video_entitlement(video_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    return await check_video_access(db, user_id, video_id)


@router.get("/entitlements/check/package/{pkg_id}", response_model=AccessStatus)
async def check_package_entitlement(pkg_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    return await check_package_access(db, user_id, pkg_id)


# ─── Orders ───────────────────────────────────────────────────────────────────
@router.post("/orders", response_model=OrderCreateResponse)
async def create_order(
    body: OrderCreateRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Secure order creation. The client sends ONLY what it wants (content,
    method, coupon). User, price, currency, USDT amount, expiry and status are
    all decided here: user_id comes from the verified Telegram-auth JWT, the
    price from the content record, the amount from the admin-set rate.
    """
    db = get_db()
    await ensure_not_in_maintenance(db)

    # Check not already has access
    already = await has_any_access(db, user_id, body.content_type, body.content_id)
    if already:
        raise HTTPException(status_code=409, detail="Already has active access")

    # Serialise this user's attempts for this content (double-tap / retry safety).
    async with _order_lock(user_id, body.content_type, body.content_id):
        return await _create_order_locked(db, body, user_id)


async def _create_order_locked(db, body: OrderCreateRequest, uid: str) -> OrderCreateResponse:
    """Runs under the per-user/content lock. `uid` is the JWT-verified user (see create_order)."""
    if body.coupon_code:
        # Second lock (always taken AFTER the content lock, so no deadlock): two
        # simultaneous orders for different content cannot both claim one coupon.
        async with _order_lock(uid, "coupon", body.coupon_code.strip().upper()):
            return await _create_order_unlocked(db, body, uid)
    return await _create_order_unlocked(db, body, uid)


async def _create_order_unlocked(db, body: OrderCreateRequest, uid: str) -> OrderCreateResponse:
    now = datetime.now(timezone.utc)

    # 2. Load content price
    col = Col.VIDEOS if body.content_type == "video" else Col.PACKAGES
    content_doc = await db.collection(col).document(body.content_id).get()
    if not content_doc.exists or not (content_doc.to_dict() or {}).get("is_published"):
        raise HTTPException(status_code=404, detail="Content not found")
    content_data = content_doc.to_dict() or {}
    if not content_data.get("purchase_enabled", True):
        raise HTTPException(status_code=400, detail="Purchase not enabled for this content")
    base_price = float(content_data.get("price_bdt", 0))

    # 3. Validate coupon if provided
    discount_bdt = 0.0
    coupon_code = None
    if body.coupon_code:
        coupon_result = await validate_coupon(
            db, body.coupon_code, uid,
            body.content_type, body.content_id, base_price,
            pending_uses=await _coupon_pending_uses(
                db, uid, body.coupon_code, body.content_type, body.content_id, now),
        )
        if not coupon_result.valid:
            raise HTTPException(status_code=400, detail=coupon_result.message)
        discount_bdt = coupon_result.discount_bdt
        coupon_code = body.coupon_code.strip().upper()

    final_bdt = max(0, base_price - discount_bdt)

    # 4. Load payment method (admin-controlled; enabled AND actually payable)
    method_doc = await db.collection(Col.PAYMENT_METHODS).document(body.payment_method_id).get()
    if not method_doc.exists:
        raise HTTPException(status_code=400, detail="Payment method not available")
    method = normalize_method(method_doc.id, method_doc.to_dict() or {})
    if not is_payable(method):
        raise HTTPException(status_code=400, detail="Payment method not available")
    gateway = is_gateway(method["type"])

    # 5. Amount in USDT — rate is the admin-set app config, never the client's
    cfg_doc = await db.collection(Col.APP_SETTINGS).document("config").get()
    cfg = cfg_doc.to_dict() if cfg_doc.exists else {}
    rate = float(cfg.get("usdt_to_bdt_rate", 115))
    final_usdt = round(final_bdt / rate, 8)

    # Method limits (min AND max)
    problem = amount_problem(method, final_usdt)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    # 6. Duplicate-order prevention
    # 6a. Payment for this content already submitted → wait for review.
    hold_q = (
        db.collection(Col.ORDERS)
        .where(filter=FieldFilter("user_id", "==", uid))
        .where(filter=FieldFilter("status", "in", ["payment_submitted", "under_review"]))
    )
    async for d in hold_q.stream():
        od = d.to_dict() or {}
        if od.get("content_type") == body.content_type and od.get("content_id") == body.content_id:
            raise HTTPException(status_code=409, detail="Payment already under review for this item")

    # 6b. Open unpaid orders for this content: reuse the identical one,
    #     retire the rest so only one payable order exists per item.
    open_q = (
        db.collection(Col.ORDERS)
        .where(filter=FieldFilter("user_id", "==", uid))
        .where(filter=FieldFilter("status", "==", "awaiting_payment"))
    )
    async for d in open_q.stream():
        od = d.to_dict() or {}
        if od.get("content_type") != body.content_type or od.get("content_id") != body.content_id:
            continue
        if od.get("expires_at") is None or od["expires_at"] <= now:
            await d.reference.update({"status": "expired"})
            continue
        same = (
            od.get("payment_method_id") == body.payment_method_id
            and (od.get("coupon_code") or None) == coupon_code
            and abs(float(od.get("final_usdt", -1)) - final_usdt) < 1e-9
        )
        if same:
            pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", d.id)).limit(1)
            pdocs = [p async for p in pq.stream()]
            if pdocs:
                pd = pdocs[0].to_dict() or {}
                return OrderCreateResponse(
                    order_id=d.id,
                    final_bdt=od.get("final_bdt", final_bdt),
                    final_usdt=od.get("final_usdt", final_usdt),
                    usdt_rate=od.get("usdt_rate_at_creation", rate),
                    expires_at=od["expires_at"],
                    payment_details=_details_from_docs(pdocs[0].id, pd, method, od["expires_at"], reused=True),
                )
        # Different method / coupon / price → the old order is superseded.
        await d.reference.update({"status": "expired", "superseded_at": now})

    # Housekeeping: persist expiry for any other overdue unpaid orders of this user.
    await _expire_user_stale_orders(db, uid, now)

    timeout_min = method["payment_timeout_minutes"]
    expires_at = now + timedelta(minutes=timeout_min)

    # 7. Create order
    order_id = str(uuid.uuid4())
    await db.collection(Col.ORDERS).document(order_id).set({
        "user_id": uid,
        "content_type": body.content_type,
        "content_id": body.content_id,
        "amount_bdt": base_price,
        "coupon_code": coupon_code,
        "discount_bdt": discount_bdt,
        "final_bdt": final_bdt,
        "usdt_rate_at_creation": rate,
        "final_usdt": final_usdt,
        "currency": method["currency"],
        "payment_method_id": body.payment_method_id,
        "payment_method_type": method["type"],
        "status": "awaiting_payment",
        "created_at": now,
        "expires_at": expires_at,
        "submitted_at": None,
        "completed_at": None,
        "entitlement_id": None,
    })

    # 8. Create payment document (a snapshot of where/how to pay at this moment,
    #    so later admin edits never change an order that is already open)
    payment_id = str(uuid.uuid4())
    binance_checkout_url = None
    binance_prepay_id = None

    if gateway:
        try:
            binance_result = await create_prepay_order(
                order_id=order_id,
                amount_usdt=final_usdt,
                description=content_data.get("title", "Video Store Purchase")[:256],
                return_url=f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}",
                cancel_url=f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}",
                webhook_url=f"{settings.PUBLIC_API_BASE_URL.rstrip('/')}/api/v1/webhooks/binance-pay",
                expire_at=expires_at,
            )
            binance_checkout_url = binance_result["checkout_url"]
            binance_prepay_id = binance_result["prepay_id"]
        except Exception as e:
            # Binance unavailable/misconfigured. Falling through would create a
            # payment with NO wallet address and NO checkout URL (unpayable),
            # so fail the order cleanly instead.
            logger.error(f"Binance prepay failed for order {order_id}: {e}")
            await db.collection(Col.ORDERS).document(order_id).update({"status": "failed"})
            raise HTTPException(
                status_code=503,
                detail="Binance Pay এখন পাওয়া যাচ্ছে না। অন্য Payment Method ব্যবহার করুন।",
            )

    pay_doc = {
        "order_id": order_id,
        "user_id": uid,
        "payment_method": method["type"],
        "payment_method_id": body.payment_method_id,
        "expected_usdt": final_usdt,
        "currency": method["currency"],
        "paid_amount_usdt": None,
        "binance_prepay_id": binance_prepay_id,
        "binance_checkout_url": binance_checkout_url,
        "binance_webhook_verified": False,
        "wallet_address": None if gateway else method["wallet_address"],
        "pay_id": None if gateway else method["pay_id"],
        "network": None if gateway else method["network_name"],
        "user_submitted_txhash": None,
        "screenshot_url": None,
        "user_note": None,
        "verification_method": VERIFY_AUTO if method["auto_verification_supported"] and gateway else VERIFY_MANUAL,
        "verification_status": "pending",
        "verified_by": None,
        "verified_at": None,
        "admin_note": None,
        "attempts": 0,
        "last_checked_at": None,
        "review_reason": None,
        "status_history": [history_event(None, "awaiting_payment", uid, "order_created",
                                         f"{method['type']} · {final_usdt} USDT", now)],
        "created_at": now,
        "updated_at": now,
    }
    await db.collection(Col.PAYMENTS).document(payment_id).set(pay_doc)

    return OrderCreateResponse(
        order_id=order_id,
        final_bdt=final_bdt,
        final_usdt=final_usdt,
        usdt_rate=rate,
        expires_at=expires_at,
        payment_details=_details_from_docs(payment_id, pay_doc, method, expires_at, reused=False),
    )


@router.get("/orders/history", response_model=dict)
async def order_history(
    user_id: str = Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    query = (
        db.collection(Col.ORDERS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("created_at", direction="DESCENDING")
    )
    if status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))
    all_docs = [d async for d in query.stream()]
    total = len(all_docs)
    start = (page - 1) * limit
    items = []
    now = datetime.now(timezone.utc)
    for d in all_docs[start:start + limit]:
        od = d.to_dict() or {}
        items.append(Order(
            id=d.id, user_id=od["user_id"],
            content_type=od["content_type"], content_id=od["content_id"],
            amount_bdt=od.get("amount_bdt", 0), coupon_code=od.get("coupon_code"),
            discount_bdt=od.get("discount_bdt", 0), final_bdt=od.get("final_bdt", 0),
            final_usdt=od.get("final_usdt", 0), usdt_rate_at_creation=od.get("usdt_rate_at_creation", 115),
            payment_method_id=od.get("payment_method_id", ""), status=_effective_order_status(od, now),
            created_at=od["created_at"], expires_at=od["expires_at"],
            completed_at=od.get("completed_at"), currency=od.get("currency", "USDT"),
            payment_method_type=od.get("payment_method_type"),
        ))
    return {"items": items, "total": total, "page": page, "has_more": start + limit < total}


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
async def get_order(order_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    order_doc = await db.collection(Col.ORDERS).document(order_id).get()
    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    od = order_doc.to_dict() or {}
    if od.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Find payment
    pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", order_id)).limit(1)
    pdocs = [d async for d in pq.stream()]
    if not pdocs:
        raise HTTPException(status_code=404, detail="Payment not found")
    pd = pdocs[0].to_dict() or {}

    now = datetime.now(timezone.utc)
    eff_status = _effective_order_status(od, now)
    if eff_status == "expired" and od.get("status") != "expired":
        # Persist so admin views / later reads agree with what the user saw.
        # Own order only; a late Binance webhook can still complete it.
        try:
            await db.collection(Col.ORDERS).document(order_id).update({"status": "expired"})
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not persist expiry for order {order_id}: {exc}")

    order = Order(
        id=order_id, user_id=od["user_id"],
        content_type=od["content_type"], content_id=od["content_id"],
        amount_bdt=od.get("amount_bdt", 0), coupon_code=od.get("coupon_code"),
        discount_bdt=od.get("discount_bdt", 0), final_bdt=od.get("final_bdt", 0),
        final_usdt=od.get("final_usdt", 0), usdt_rate_at_creation=od.get("usdt_rate_at_creation", 115),
        payment_method_id=od.get("payment_method_id", ""), status=eff_status,
        created_at=od["created_at"], expires_at=od["expires_at"],
        completed_at=od.get("completed_at"), currency=od.get("currency", "USDT"),
        payment_method_type=od.get("payment_method_type"),
    )
    payment = Payment(
        id=pdocs[0].id, order_id=order_id,
        payment_method=pd.get("payment_method", ""),
        expected_usdt=pd.get("expected_usdt", 0),
        paid_amount_usdt=pd.get("paid_amount_usdt"),
        binance_checkout_url=pd.get("binance_checkout_url"),
        wallet_address=pd.get("wallet_address"),
        network=pd.get("network"),
        verification_method=pd.get("verification_method", "manual"),
        verification_status=pd.get("verification_status", "pending"),
        created_at=pd["created_at"],
        review_code=review_code(eff_status, pd),
        attempts=int(pd.get("attempts") or 0),
        last_checked_at=pd.get("last_checked_at"),
        pay_id=pd.get("pay_id"),
    )

    # Admin-configured screen data (instructions, QR, Pay ID, merchant, limits) —
    # the order's own snapshot wins; the method document fills the gaps. Best
    # effort: a missing / deleted method never breaks the status screen.
    details = None
    try:
        mdoc = await db.collection(Col.PAYMENT_METHODS).document(od.get("payment_method_id", "")).get()
        if mdoc.exists:
            method = normalize_method(mdoc.id, mdoc.to_dict() or {})
            details = _details_from_docs(pdocs[0].id, pd, method, od["expires_at"], reused=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Payment details unavailable for order {order_id}: {exc}")

    # Retry availability (only computed where the screen can use it)
    retry = RetryInfo()
    if eff_status in ("expired", "failed"):
        try:
            cfg = await payment_settings(db)
            recent = await _recent_unpaid_count(db, user_id, od["content_type"], od["content_id"], now)
            has_access = await has_any_access(db, user_id, od["content_type"], od["content_id"])
            retry = RetryInfo(**retry_info(eff_status, recent, cfg["retry_limit_24h"], has_access))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Retry info unavailable for order {order_id}: {exc}")
            retry = RetryInfo(allowed=True)   # the retry endpoint itself enforces the real rules

    return OrderDetailResponse(
        order=order, payment=payment, details=details,
        timeline=[TimelineEvent(**e) for e in public_timeline(pd.get("status_history"))],
        retry=retry,
    )


@router.post("/orders/{order_id}/submit", response_model=PaymentSubmitResponse)
async def submit_payment(
    order_id: str,
    body: PaymentSubmitRequest,
    user_id: str = Depends(get_current_user),
):
    # Double-tap / duplicate-request protection: one submit per order at a time;
    # the status is re-read INSIDE the lock, so the second request sees
    # `under_review` and gets a clean 409 instead of writing twice.
    async with _order_lock(user_id, "submit", order_id):
        return await _submit_payment_locked(order_id, body, user_id)


async def _submit_payment_locked(order_id: str, body: PaymentSubmitRequest, uid: str) -> PaymentSubmitResponse:
    """Runs under the per-order lock. `uid` is the JWT-verified user (see submit_payment)."""
    db = get_db()
    order_doc = await db.collection(Col.ORDERS).document(order_id).get()
    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    od = order_doc.to_dict() or {}
    if od["user_id"] != uid:
        raise HTTPException(status_code=403, detail="Forbidden")
    if od["status"] in ("completed", "failed", "refunded"):
        raise HTTPException(status_code=409, detail="Order already processed")
    if od["status"] == "expired":
        raise HTTPException(status_code=400, detail="Order expired")
    if od["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Order expired")
    if od["status"] in ("payment_submitted", "under_review"):
        raise HTTPException(status_code=409, detail="Payment already submitted")

    now = datetime.now(timezone.utc)

    pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", order_id)).limit(1)
    pdocs = [d async for d in pq.stream()]
    method_type = (pdocs[0].to_dict() or {}).get("payment_method", "") if pdocs else ""

    # Transaction hash: right shape for the network, one canonical spelling, and
    # one order per hash EVER (atomic claim — also stops two simultaneous submits).
    txhash = normalize_txhash(method_type, body.transaction_hash)
    if txhash:
        bad = txhash_problem(method_type, txhash)
        if bad:
            raise HTTPException(status_code=422, detail=bad)
        dup_q = (
            db.collection(Col.PAYMENTS)
            .where(filter=FieldFilter("user_submitted_txhash", "==", txhash))
            .limit(2)
        )
        if [d for d in [x async for x in dup_q.stream()] if (d.to_dict() or {}).get("order_id") != order_id]:
            raise HTTPException(status_code=409, detail="Transaction hash already used")
        if not await claim_txhash(db, txhash, payment_id=pdocs[0].id if pdocs else "", order_id=order_id, user_id=uid):
            raise HTTPException(status_code=409, detail="Transaction hash already used")

    # Update payment (the user's txhash / screenshot are CLAIMS for the admin to check, never proof)
    if pdocs:
        await pdocs[0].reference.update({
            "user_submitted_txhash": txhash,
            "screenshot_url": body.screenshot_url,
            "user_note": body.user_note,
            "updated_at": now,
        })
        await append_history(
            pdocs[0].reference,
            history_event(od["status"], "under_review", uid, "user_submit",
                          "tx hash" if txhash else "screenshot only", now),
        )

    # Update order status
    await db.collection(Col.ORDERS).document(order_id).update({
        "status": "under_review",
        "submitted_at": now,
    })

    # Notify admin via Firestore (admin panel will pick this up)
    await audit_log(
        action="payment_submitted",
        performed_by=uid,
        target_type="order",
        target_id=order_id,
        after={"transaction_hash": txhash},
    )

    return PaymentSubmitResponse(status="under_review", message="Payment জমা হয়েছে। Admin যাচাই করবেন।")


# ─── Verify (Binance Pay) & Retry — Phase 10 Part 2A ──────────────────────────
_VERIFY_MESSAGES = {
    "fulfilled": "Payment যাচাই হয়েছে ✅ আপনার Access চালু হয়েছে।",
    "review": "Payment পাওয়া গেছে, তবে Admin যাচাই করবেন।",
    "failed": "Binance এই Payment বন্ধ/বাতিল করেছে। নতুন করে চেষ্টা করুন।",
    "wait": "এখনো Payment নিশ্চিত হয়নি। Binance-এ পেমেন্ট শেষ করে কিছুক্ষণ পর আবার দেখুন।",
    "noop": "অর্ডারটি ইতোমধ্যে সম্পন্ন বা বন্ধ।",
}


@router.post("/orders/{order_id}/verify", response_model=PaymentVerifyResponse)
async def verify_order_payment(order_id: str, user_id: str = Depends(get_current_user)):
    """
    "Check my payment" for Binance Pay orders — the fallback when the webhook is
    late or missed. The answer comes from Binance's signed API, NOT from the
    client: calling this can never grant access by itself. Throttled per payment
    (admin-set `payment_verify_min_interval_seconds`).
    """
    db = get_db()
    order_doc = await db.collection(Col.ORDERS).document(order_id).get()
    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    od = order_doc.to_dict() or {}
    if od.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if od.get("status") == "completed":
        return PaymentVerifyResponse(status="completed", outcome="noop", message=_VERIFY_MESSAGES["noop"],
                                     entitlement_id=od.get("entitlement_id"))

    pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", order_id)).limit(1)
    pdocs = [d async for d in pq.stream()]
    if not pdocs:
        raise HTTPException(status_code=404, detail="Payment not found")
    pd = pdocs[0].to_dict() or {}
    if not is_gateway(pd.get("payment_method", "")):
        # On-chain / Pay ID / custom: nothing the API can confirm — an admin reviews.
        return PaymentVerifyResponse(status=od.get("status", "awaiting_payment"), outcome="manual",
                                     message="এই পদ্ধতিতে Admin Payment যাচাই করেন।")

    now = datetime.now(timezone.utc)
    cfg = await payment_settings(db)
    wait = verify_wait_seconds(pd, now, cfg["verify_min_interval_s"])
    if wait:
        raise HTTPException(status_code=429, detail=f"{wait} সেকেন্ড পর আবার চেষ্টা করুন।", headers={"Retry-After": str(wait)})

    try:
        res = await verify_binance_order(db, order_id, source="user_check", actor=user_id)
    except BinanceUnavailable as exc:
        logger.warning(f"Binance verify unavailable for order {order_id}: {exc}")
        raise HTTPException(status_code=503, detail="Binance এখন যাচাই করা যাচ্ছে না। কিছুক্ষণ পর আবার চেষ্টা করুন।")
    outcome = res["outcome"] if res["outcome"] in _VERIFY_MESSAGES else "noop"
    return PaymentVerifyResponse(
        status=res.get("order_status") or od.get("status", "awaiting_payment"),
        outcome=outcome, message=_VERIFY_MESSAGES[outcome], entitlement_id=res.get("entitlement_id"),
    )


@router.post("/orders/{order_id}/retry", response_model=OrderCreateResponse)
async def retry_order(
    order_id: str,
    body: OrderRetryRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Pay again after an expired / failed order: creates a NEW order (new unique id,
    price + USDT amount recomputed by the backend, same content and coupon) —
    optionally with another method. The old order and its history stay untouched.
    The number of retries per item per 24h is an admin setting (`payment_retry_limit_24h`).
    """
    db = get_db()
    await ensure_not_in_maintenance(db)
    old_doc = await db.collection(Col.ORDERS).document(order_id).get()
    if not old_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    old = old_doc.to_dict() or {}
    if old.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    now = datetime.now(timezone.utc)
    if _effective_order_status(old, now) not in ("expired", "failed"):
        raise HTTPException(status_code=409, detail="Only an expired or failed order can be retried")

    ctype, cid = old["content_type"], old["content_id"]
    if await has_any_access(db, user_id, ctype, cid):
        raise HTTPException(status_code=409, detail="Already has active access")

    cfg = await payment_settings(db)
    recent = await _recent_unpaid_count(db, user_id, ctype, cid, now)
    if retry_limit_reached(recent, cfg["retry_limit_24h"]):
        raise HTTPException(status_code=429, detail="অনেকবার চেষ্টা করা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন বা Support-এ যোগাযোগ করুন।")

    req = OrderCreateRequest(
        content_type=ctype, content_id=cid,
        payment_method_id=body.payment_method_id or old.get("payment_method_id", ""),
        coupon_code=old.get("coupon_code"),
    )
    async with _order_lock(user_id, ctype, cid):
        resp = await _create_order_locked(db, req, user_id)
    await audit_log(
        action="payment_retry", performed_by=user_id, target_type="order", target_id=resp.order_id,
        before={"previous_order_id": order_id, "previous_status": old.get("status")},
        after={"payment_method_id": req.payment_method_id},
    )
    return resp
