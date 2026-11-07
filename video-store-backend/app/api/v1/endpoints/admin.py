"""
Admin endpoints — manual payment review.

Auth: POST /admin/login lives in admin_auth.py → short-lived admin JWT. Every route
here requires that token (get_current_admin) AND a role permission
(require_permission). User tokens are rejected (and vice versa).
"""
from datetime import datetime, timezone

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, Field, field_validator

from app.core.admin_roles import Perm
from app.core.deps import get_current_admin, require_permission
from app.db.firebase import get_db, Col
from app.services.ad_providers import get_provider, provider_types
from app.services.fulfillment import fulfill_order
from app.services.binance import BinanceUnavailable
from app.services.payment_methods import is_gateway
from app.services.payment_verification import history_event, append_history, verify_binance_order
from app.utils.audit import audit_log, create_notification

router = APIRouter(prefix="/admin", tags=["admin"])


class PaymentDecisionRequest(BaseModel):
    admin_note: str | None = Field(default=None, max_length=500)
    # Optional on approve: what the admin actually saw arrive. If given it must cover
    # the amount the backend asked for (an underpaid order cannot be approved).
    paid_amount_usdt: float | None = Field(default=None, gt=0)


async def _load_order_and_payment(db, order_id: str):
    order_doc = await db.collection(Col.ORDERS).document(order_id).get()
    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", order_id)).limit(1)
    pdocs = [d async for d in pq.stream()]
    if not pdocs:
        raise HTTPException(status_code=404, detail="Payment not found")
    return order_doc.to_dict() or {}, pdocs[0]


@router.get("/payments/pending", dependencies=[Depends(require_permission(Perm.PAYMENTS_REVIEW))])
async def list_pending_payments(
    admin: str = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    q = db.collection(Col.ORDERS).where(filter=FieldFilter("status", "==", "under_review"))
    docs = [d async for d in q.stream()]
    docs.sort(key=lambda d: (d.to_dict() or {}).get("submitted_at") or datetime.min.replace(tzinfo=timezone.utc))
    total = len(docs)
    start = (page - 1) * limit
    items = []
    for d in docs[start:start + limit]:
        od = d.to_dict() or {}
        pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", d.id)).limit(1)
        pdocs = [p async for p in pq.stream()]
        pd = (pdocs[0].to_dict() or {}) if pdocs else {}
        items.append({
            "order_id": d.id,
            "user_id": od.get("user_id"),
            "content_type": od.get("content_type"),
            "content_id": od.get("content_id"),
            "final_bdt": od.get("final_bdt"),
            "final_usdt": od.get("final_usdt"),
            "submitted_at": od.get("submitted_at"),
            "payment_method": pd.get("payment_method"),
            "transaction_hash": pd.get("user_submitted_txhash"),
            "screenshot_url": pd.get("screenshot_url"),
            "user_note": pd.get("user_note"),
            "review_reason": pd.get("review_reason"),
        })
    return {"items": items, "total": total, "page": page, "has_more": start + limit < total}


@router.post("/payments/{order_id}/approve", dependencies=[Depends(require_permission(Perm.PAYMENTS_REVIEW))])
async def approve_payment(
    order_id: str,
    body: PaymentDecisionRequest,
    admin: str = Depends(get_current_admin),
):
    db = get_db()
    od, pay_doc = await _load_order_and_payment(db, order_id)
    if od.get("status") == "completed":
        return {"status": "completed", "message": "Already approved"}
    if od.get("status") in ("refunded",):
        raise HTTPException(status_code=409, detail="Order refunded")
    if od.get("status") != "under_review":
        raise HTTPException(status_code=409, detail="Order is not awaiting review")

    now = datetime.now(timezone.utc)
    if body.paid_amount_usdt is not None:
        from app.core.webhook_utils import amount_covers
        if not amount_covers(float(od.get("final_usdt") or 0), body.paid_amount_usdt):
            raise HTTPException(status_code=422, detail="Paid amount is less than the expected amount")
    update = {
        "verification_status": "verified",
        "verified_by": admin,
        "verified_at": now,
        "admin_note": body.admin_note,
        "updated_at": now,
    }
    if body.paid_amount_usdt is not None:
        update["paid_amount_usdt"] = body.paid_amount_usdt
    await pay_doc.reference.update(update)
    await append_history(pay_doc.reference, history_event(od.get("status"), "verified", admin, "admin_approve", body.admin_note, now))
    ent_id = await fulfill_order(db, order_id)
    if ent_id is None:
        # e.g. a rejection raced this approval — nothing was granted, say so honestly.
        raise HTTPException(status_code=409, detail="Order could not be fulfilled (state changed); no access was granted")
    await audit_log(
        action="payment_approved", performed_by=admin,
        target_type="order", target_id=order_id,
        before={"status": od.get("status")},
        after={"entitlement_id": ent_id, "note": body.admin_note},
    )
    return {"status": "completed", "entitlement_id": ent_id}


@router.post("/payments/{order_id}/reject", dependencies=[Depends(require_permission(Perm.PAYMENTS_REVIEW))])
async def reject_payment(
    order_id: str,
    body: PaymentDecisionRequest,
    admin: str = Depends(get_current_admin),
):
    db = get_db()
    od, pay_doc = await _load_order_and_payment(db, order_id)
    if od.get("status") != "under_review":
        raise HTTPException(status_code=409, detail="Order is not awaiting review")

    now = datetime.now(timezone.utc)
    await pay_doc.reference.update({
        "verification_status": "failed",
        "verified_by": admin,
        "verified_at": now,
        "admin_note": body.admin_note,
        "updated_at": now,
    })
    await db.collection(Col.ORDERS).document(order_id).update({"status": "failed"})
    await append_history(pay_doc.reference, history_event(od.get("status"), "rejected", admin, "admin_reject", body.admin_note, now))
    await create_notification(
        user_id=od["user_id"],
        type_="payment_rejected",
        title="Payment যাচাই হয়নি ❌",
        body="আপনার Payment যাচাই করা যায়নি। Support-এ যোগাযোগ করুন।",
        action_type="open_order",
        action_id=order_id,
    )
    await audit_log(
        action="payment_rejected", performed_by=admin,
        target_type="order", target_id=order_id,
        before={"status": od.get("status")},
        after={"note": body.admin_note},
    )
    return {"status": "failed"}


@router.get("/payments/{order_id}", dependencies=[Depends(require_permission(Perm.PAYMENTS_REVIEW))])
async def payment_detail(order_id: str, admin: str = Depends(get_current_admin)):
    """One payment for review: order + payment snapshot + full status history."""
    db = get_db()
    od, pay_doc = await _load_order_and_payment(db, order_id)
    pd = pay_doc.to_dict() or {}
    history = sorted(pd.get("status_history") or [], key=lambda e: e.get("at") or datetime.min.replace(tzinfo=timezone.utc))
    return {
        "order": {k: od.get(k) for k in (
            "user_id", "content_type", "content_id", "final_bdt", "final_usdt", "usdt_rate_at_creation",
            "status", "created_at", "expires_at", "submitted_at", "completed_at", "entitlement_id", "coupon_code")},
        "payment": {
            "id": pay_doc.id,
            **{k: pd.get(k) for k in (
                "payment_method", "payment_method_id", "expected_usdt", "paid_amount_usdt", "wallet_address",
                "pay_id", "network", "user_submitted_txhash", "screenshot_url", "user_note",
                "verification_method", "verification_status", "verified_by", "verified_at", "admin_note",
                "review_reason", "binance_last_status", "attempts", "last_checked_at", "created_at")},
        },
        "status_history": history,
    }


@router.post("/payments/{order_id}/reverify", dependencies=[Depends(require_permission(Perm.PAYMENTS_REVIEW))])
async def reverify_payment(order_id: str, admin: str = Depends(get_current_admin)):
    """
    Ask Binance again about a Binance Pay order (e.g. a payment held in review,
    or a missed webhook). Same verifier as the webhook; it can complete the
    order only when Binance itself confirms an exactly-matching payment.
    """
    db = get_db()
    od, pay_doc = await _load_order_and_payment(db, order_id)
    if not is_gateway((pay_doc.to_dict() or {}).get("payment_method", "")):
        raise HTTPException(status_code=400, detail="Only Binance Pay orders can be re-verified by API")
    try:
        res = await verify_binance_order(db, order_id, source="admin_reverify", actor=admin)
    except BinanceUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Binance unavailable: {exc}")
    await audit_log(
        action="payment_reverified", performed_by=admin, target_type="order", target_id=order_id,
        before={"status": od.get("status")}, after={k: res.get(k) for k in ("outcome", "reason", "order_status")},
    )
    return res


# ─── Ad networks (provider configuration) ─────────────────────────────────────
# Only NON-secret settings live in Firestore. Secrets stay in backend env vars;
# the document stores just the setting NAME (`s2s_callback_secret_ref`), which
# the provider module owns and this endpoint never accepts from the client.
_AD_PLACEMENTS = ("video_unlock", "package_unlock", "rewarded")


class AdNetworkUpdate(BaseModel):
    """Partial update: only the fields sent are written (merge)."""
    name: str | None = Field(default=None, min_length=1, max_length=64)
    type: str | None = Field(default=None, max_length=32)          # provider id
    is_enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)      # lower = first
    zone_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    sdk_url: str | None = Field(default=None, max_length=300)
    placements: dict[str, bool] | None = None
    default_ads_required: int | None = Field(default=None, ge=1, le=50)
    unlock_duration_hours: int | None = Field(default=None, ge=0, le=24 * 365 * 10)  # 0 = lifetime
    session_timeout_minutes: int | None = Field(default=None, ge=1, le=240)

    @field_validator("sdk_url")
    @classmethod
    def _https_only(cls, v):
        if v and not v.startswith("https://"):
            raise ValueError("sdk_url must start with https://")
        return v

    @field_validator("placements")
    @classmethod
    def _known_placements(cls, v):
        if v is not None and any(k not in _AD_PLACEMENTS for k in v):
            raise ValueError(f"placements keys must be in {list(_AD_PLACEMENTS)}")
        return v


def _ad_network_view(nid: str, n: dict) -> dict:
    # Never returns anything secret-like; only the secret's setting NAME.
    keys = ("name", "type", "is_enabled", "priority", "zone_id", "sdk_url", "placements",
            "default_ads_required", "unlock_duration_hours", "session_timeout_minutes",
            "s2s_callback_supported", "s2s_callback_secret_ref")
    return {"id": nid, **{k: n.get(k) for k in keys}}


@router.get("/ad-networks", dependencies=[Depends(require_permission(Perm.ADS_MANAGE))])
async def list_ad_networks(admin: str = Depends(get_current_admin)):
    db = get_db()
    nets = [_ad_network_view(d.id, d.to_dict() or {}) async for d in db.collection(Col.AD_NETWORKS).stream()]
    nets.sort(key=lambda n: (n.get("priority") if isinstance(n.get("priority"), int) else 1000, n["id"]))
    return {"networks": nets, "available_providers": provider_types(), "placements": list(_AD_PLACEMENTS)}


@router.put("/ad-networks/{network_id}", dependencies=[Depends(require_permission(Perm.ADS_MANAGE))])
async def upsert_ad_network(
    network_id: str,
    body: AdNetworkUpdate,
    admin: str = Depends(get_current_admin),
):
    """Create or update one network (merge — existing fields not sent are kept)."""
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", network_id):
        raise HTTPException(status_code=400, detail="Invalid network id")
    db = get_db()
    ref = db.collection(Col.AD_NETWORKS).document(network_id)
    snap = await ref.get()
    before = (snap.to_dict() or {}) if snap.exists else {}

    changes = body.model_dump(exclude_none=True)
    merged = {**before, **changes}
    provider = get_provider(merged.get("type"))
    if provider is None:
        raise HTTPException(status_code=400, detail=f"type must be one of {provider_types()}")

    # S2S capability and the secret NAME come from the provider module, not the client.
    changes["s2s_callback_supported"] = provider.supports_s2s
    changes["s2s_callback_secret_ref"] = provider.secret_setting
    merged.update(changes)
    if merged.get("is_enabled") is True:
        problems = provider.config_problems(merged)
        if problems:
            raise HTTPException(status_code=400, detail="Cannot enable: " + "; ".join(problems))

    now = datetime.now(timezone.utc)
    changes["updated_at"] = now
    if not snap.exists:
        changes.setdefault("created_at", now)
        changes.setdefault("is_enabled", False)   # new networks start disabled
    await ref.set(changes, merge=True)
    await audit_log(
        action="ad_network_updated", performed_by=admin,
        target_type="ad_network", target_id=network_id,
        before={k: before.get(k) for k in changes if k in before and k != "updated_at"},
        after={k: v for k, v in changes.items() if k != "updated_at"},
    )
    return {"status": "ok", "network": _ad_network_view(network_id, {**before, **changes})}
