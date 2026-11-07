"""
Admin — Payment Method configuration + order-expiry sweep (Phase 10).

Same admin auth as admin.py (get_current_admin; user tokens are rejected).
Methods live in the existing `payment_methods` collection. Binance API
credentials are NEVER stored here (they stay in server env vars); this API only
manages what users see: wallet / Pay ID, network, limits, instructions, flags.
"""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, Field

from app.core.admin_roles import Perm
from app.core.deps import get_current_admin, require_permission
from app.db.firebase import get_db, Col
from app.services.payment_methods import (
    normalize_method, is_payable, config_problems, METHOD_TYPES,
)
from app.services.payment_verification import history_event, append_history
from app.utils.audit import audit_log

router = APIRouter(prefix="/admin", tags=["admin-payment-methods"])

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

# Fields an admin may set. Anything else in a request body is rejected by Pydantic.
_FIELDS = (
    "name", "type", "is_enabled", "display_order", "network_name", "wallet_address",
    "pay_id", "merchant_name", "qr_code_url", "currency", "min_amount_usdt",
    "max_amount_usdt", "payment_timeout_minutes", "instructions_text",
    "auto_verification_supported", "manual_review_supported",
)


class PaymentMethodUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    id: str | None = Field(default=None, description="Unique method ID (create only); auto-generated if omitted")
    name: str | None = Field(default=None, max_length=80)
    type: str | None = Field(default=None, max_length=32)
    is_enabled: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=10_000)
    network_name: str | None = Field(default=None, max_length=60)
    wallet_address: str | None = Field(default=None, max_length=200)
    pay_id: str | None = Field(default=None, max_length=40)
    merchant_name: str | None = Field(default=None, max_length=80)
    qr_code_url: str | None = Field(default=None, max_length=1000)
    currency: str | None = Field(default=None, min_length=2, max_length=10)
    min_amount_usdt: float | None = Field(default=None, ge=0)
    max_amount_usdt: float | None = Field(default=None, gt=0)
    payment_timeout_minutes: int | None = None
    instructions_text: str | None = Field(default=None, max_length=2000)
    auto_verification_supported: bool | None = None
    manual_review_supported: bool | None = None


class EnabledRequest(BaseModel):
    is_enabled: bool


def _admin_view(doc_id: str, data: dict) -> dict:
    m = normalize_method(doc_id, data)
    m["payable"] = is_payable({**m, "is_enabled": True})
    m["problems"] = config_problems({**data, "type": m["type"], "name": m["name"]})
    return m


@router.get("/payment-methods", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_list_payment_methods(admin: str = Depends(get_current_admin)):
    db = get_db()
    items = [_admin_view(d.id, d.to_dict() or {}) async for d in db.collection(Col.PAYMENT_METHODS).stream()]
    items.sort(key=lambda m: (m["display_order"], m["id"]))
    return {"methods": items, "builtin_types": sorted(METHOD_TYPES)}


@router.post("/payment-methods", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_create_payment_method(
    body: PaymentMethodUpsert, admin: str = Depends(get_current_admin),
):
    data = {k: getattr(body, k) for k in _FIELDS if getattr(body, k) is not None}
    data.setdefault("is_enabled", False)       # new methods start disabled until reviewed
    data.setdefault("display_order", 100)
    problems = config_problems(data)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))

    method_id = body.id or f"{data['type']}_{uuid.uuid4().hex[:6]}"
    if not _ID_RE.match(method_id):
        raise HTTPException(status_code=422, detail="id must be 2–64 chars: a-z, 0-9, _ or -")
    data["created_at"] = data["updated_at"] = datetime.now(timezone.utc)

    db = get_db()
    try:
        await db.collection(Col.PAYMENT_METHODS).document(method_id).create(data)   # never overwrites
    except AlreadyExists:
        raise HTTPException(status_code=409, detail="Method ID already exists")
    await audit_log(
        action="payment_method_created", performed_by=admin,
        target_type="payment_method", target_id=method_id,
        after={k: v for k, v in data.items() if k not in ("created_at", "updated_at")},
    )
    return _admin_view(method_id, data)


@router.put("/payment-methods/{method_id}", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_update_payment_method(
    method_id: str, body: PaymentMethodUpsert, admin: str = Depends(get_current_admin),
):
    """Partial update: only the fields sent are changed; the merged result is validated."""
    if body.id and body.id != method_id:
        raise HTTPException(status_code=422, detail="Method ID cannot be changed")
    db = get_db()
    ref = db.collection(Col.PAYMENT_METHODS).document(method_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Method not found")
    before = snap.to_dict() or {}
    changes = {k: getattr(body, k) for k in _FIELDS if k in body.model_fields_set}
    merged = {**before, **changes}
    problems = config_problems(merged)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    changes["updated_at"] = datetime.now(timezone.utc)
    await ref.update(changes)
    await audit_log(
        action="payment_method_updated", performed_by=admin,
        target_type="payment_method", target_id=method_id,
        before={k: before.get(k) for k in changes if k != "updated_at"},
        after={k: v for k, v in changes.items() if k != "updated_at"},
    )
    return _admin_view(method_id, {**merged, "updated_at": changes["updated_at"]})


@router.patch("/payment-methods/{method_id}/enabled", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_set_method_enabled(
    method_id: str, body: EnabledRequest, admin: str = Depends(get_current_admin),
):
    db = get_db()
    ref = db.collection(Col.PAYMENT_METHODS).document(method_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Method not found")
    before = snap.to_dict() or {}
    merged = {**before, "is_enabled": body.is_enabled}
    if body.is_enabled:                                   # cannot enable a broken method
        problems = config_problems(merged)
        if problems:
            raise HTTPException(status_code=422, detail="; ".join(problems))
    await ref.update({"is_enabled": body.is_enabled, "updated_at": datetime.now(timezone.utc)})
    await audit_log(
        action="payment_method_enabled" if body.is_enabled else "payment_method_disabled",
        performed_by=admin, target_type="payment_method", target_id=method_id,
        before={"is_enabled": before.get("is_enabled")}, after={"is_enabled": body.is_enabled},
    )
    return _admin_view(method_id, merged)


@router.post("/orders/expire-stale", dependencies=[Depends(require_permission(Perm.PAYMENTS_REVIEW))])
async def admin_expire_stale_orders(
    admin: str = Depends(get_current_admin),
    limit: int = Query(500, ge=1, le=1000),
):
    """
    Sweep: persist `expired` on unpaid orders past their deadline. There is no
    scheduler, so call this from a cron (e.g. Render cron job) — users also get
    the same result lazily on GET /orders/:id and on their next order attempt.
    Orders already submitted for review are never touched.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    q = db.collection(Col.ORDERS).where(filter=FieldFilter("status", "==", "awaiting_payment"))
    expired = scanned = 0
    async for d in q.stream():
        scanned += 1
        exp = (d.to_dict() or {}).get("expires_at")
        if exp is not None and exp < now:
            await d.reference.update({"status": "expired"})
            expired += 1
            # history on the payment record (best effort; one extra read per expired order)
            pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", d.id)).limit(1)
            async for pdoc in pq.stream():
                await append_history(pdoc.reference, history_event("awaiting_payment", "expired", admin, "expiry_sweep", None, now))
            if expired >= limit:
                break
    if expired:
        await audit_log(
            action="orders_expired_sweep", performed_by=admin,
            target_type="order", target_id="sweep", after={"expired": expired},
        )
    return {"scanned": scanned, "expired": expired}
