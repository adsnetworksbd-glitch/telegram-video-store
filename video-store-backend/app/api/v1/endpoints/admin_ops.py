"""
Admin operations API (Phase 12 / Part 1D) — dashboard, orders & transactions, users, support,
audit log, categories and admin accounts. Same admin JWT / role permissions, same Firestore
collections as the rest of the backend (no new collection, no schema change).

  Dashboard   GET /admin/dashboard                                    dashboard.view
  Orders      GET /admin/orders[/{id}] · /admin/transactions          orders.view   (review: existing /admin/payments/*)
  Users       GET /admin/users[/{uid}]                                users.view    (ban / access: Part 1C routes)
  Support     /admin/support/tickets[/{id}[/reply|/status]] · /admin/faqs   support.manage
  Audit       GET /admin/audit-logs                                   audit.view
  Categories  /admin/categories[/{id}[/recount]]                      videos.view · videos.manage
  Admins      /admin/admins[/{username}[/password]]                   admins.manage (super admin only)

Read views are whitelists; audit snapshots are redacted; password hashes never leave the server.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, Field

from app.core.admin_roles import AdminContext, Perm, ROLES, SUPER_ADMIN
from app.core.config import settings
from app.core.deps import get_admin_context, get_current_admin, require_permission
from app.core.security import hash_password
from app.db.firebase import Col, get_db
from app.services import admin_config as cfg
from app.services import admin_ops as O
from app.services.access_rules import entitlement_state
from app.services.admin_auth import USERNAME_RE, normalize_username
from app.utils.audit import audit_log, create_notification

router = APIRouter(prefix="/admin", tags=["admin-ops"])

_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DESC = "DESCENDING"


# ─── Shared helpers ───────────────────────────────────────────────────────────
def _422(problems: list[str]):
    raise HTTPException(status_code=422, detail="; ".join(problems))


def _sent(body: BaseModel) -> dict:
    return {k: getattr(body, k) for k in body.model_fields_set}


def _page(items: list, page: int, limit: int) -> dict:
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": len(items), "page": page, "has_more": start + limit < len(items)}


def _check_id(value: str, what: str = "id") -> None:
    if not _ID_RE.match(value or ""):
        raise HTTPException(status_code=422, detail=f"Invalid {what}")


async def _scan(db, collection: str, *, eq: tuple[str, object] | None = None, cap: int = 2000,
                order_field: str = "created_at") -> list[tuple[str, dict]]:
    """Newest `cap` documents (optionally one server-side equality filter; needs the matching index)."""
    q = db.collection(collection)
    if eq is not None:
        q = q.where(filter=FieldFilter(eq[0], "==", eq[1]))
    q = q.order_by(order_field, direction=_DESC).limit(cap)
    return [(d.id, d.to_dict() or {}) async for d in q.stream()]


async def _count(query) -> int | None:
    """Server-side count aggregation; None (not 0) when unavailable so the UI can show '—'."""
    try:
        res = await query.count(alias="n").get()
        return int(res[0][0].value)
    except Exception:
        return None


# ═══ Dashboard ════════════════════════════════════════════════════════════════
async def _safe(coro):
    """A failing optional dashboard section becomes None (UI shows '—') instead of failing the page."""
    try:
        return await coro
    except Exception:
        return None


async def _top_videos(db, limit: int = 5) -> list[dict]:
    q = db.collection(Col.VIDEOS).order_by("purchase_count", direction=_DESC).limit(limit)
    return [{"id": d.id, **O.video_stat_view(d.to_dict() or {})} async for d in q.stream()]


@router.get("/dashboard", dependencies=[Depends(require_permission(Perm.DASHBOARD_VIEW))])
async def admin_dashboard(ctx: AdminContext = Depends(get_admin_context)):
    db = get_db()
    now = _NOW()
    since = now - timedelta(days=O.DASHBOARD_WINDOW_DAYS)
    oq = (db.collection(Col.ORDERS).where(filter=FieldFilter("created_at", ">=", since))
          .order_by("created_at", direction=_DESC).limit(O.DASHBOARD_ORDER_CAP))
    orders = [d.to_dict() or {} async for d in oq.stream()]
    summary = O.summarize_orders(orders, now)
    summary["truncated"] = len(orders) >= O.DASHBOARD_ORDER_CAP     # revenue is a lower bound when true

    (users, new_users, videos, pub_videos, feat_videos, trend_videos, pkgs, pub_pkgs, cats, vis_cats,
     banned, tickets) = await asyncio.gather(
        _count(db.collection(Col.USERS)),
        _count(db.collection(Col.USERS).where(filter=FieldFilter("created_at", ">=", now - timedelta(days=7)))),
        _count(db.collection(Col.VIDEOS)),
        _count(db.collection(Col.VIDEOS).where(filter=FieldFilter("is_published", "==", True))),
        _count(db.collection(Col.VIDEOS).where(filter=FieldFilter("is_featured", "==", True))),
        _count(db.collection(Col.VIDEOS).where(filter=FieldFilter("is_trending", "==", True))),
        _count(db.collection(Col.PACKAGES)),
        _count(db.collection(Col.PACKAGES).where(filter=FieldFilter("is_published", "==", True))),
        _count(db.collection(Col.CATEGORIES)),
        _count(db.collection(Col.CATEGORIES).where(filter=FieldFilter("is_visible", "==", True))),
        _count(db.collection(Col.USERS).where(filter=FieldFilter("is_banned", "==", True))),
        _count(db.collection(Col.SUPPORT_TICKETS).where(filter=FieldFilter("status", "in", ["open", "in_progress"]))),
    )
    out = {
        "generated_at": now,
        "orders": summary,
        "users": {"total": users, "new_last_7_days": new_users, "banned": banned},
        "catalog": {"videos_total": videos, "videos_published": pub_videos,
                    "videos_hidden": (videos - pub_videos) if videos is not None and pub_videos is not None else None,
                    "videos_featured": feat_videos, "videos_trending": trend_videos,
                    "packages_total": pkgs, "packages_published": pub_pkgs,
                    "categories_total": cats, "categories_visible": vis_cats},
        "support": {"open_tickets": tickets},
        # Role-gated sections: a role only receives the data its own permission already allows it to read.
        "top_videos": None, "recent_orders": None, "recent_activity": None,
    }
    if ctx.can(Perm.VIDEOS_VIEW):
        out["top_videos"] = await _safe(_top_videos(db))
    if ctx.can(Perm.ORDERS_VIEW):
        rows = await _safe(_scan(db, Col.ORDERS, cap=O.DASHBOARD_RECENT_ORDERS))
        out["recent_orders"] = None if rows is None else [O.order_admin_view(i, d) for i, d in rows]
    if ctx.can(Perm.AUDIT_VIEW):
        rows = await _safe(_scan(db, Col.AUDIT_LOGS, cap=O.DASHBOARD_RECENT_ACTIVITY))
        out["recent_activity"] = None if rows is None else [O.audit_admin_view(i, d) for i, d in rows]
    return out


# ═══ Orders & transactions ════════════════════════════════════════════════════
@router.get("/orders", dependencies=[Depends(require_permission(Perm.ORDERS_VIEW))])
async def admin_list_orders(
    admin: str = Depends(get_current_admin),
    status: Literal[O.ORDER_STATUSES] | None = Query(None),     # type: ignore[valid-type]
    uid: str | None = Query(None, alias="user_id", max_length=128),
    content_type: Literal["video", "package"] | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    if uid:
        _check_id(uid, "user id")
    eq = ("user_id", uid) if uid else (("status", status) if status else None)
    rows = await _scan(db, Col.ORDERS, eq=eq)
    if uid and status:
        rows = [r for r in rows if r[1].get("status") == status]
    if content_type:
        rows = [r for r in rows if r[1].get("content_type") == content_type]
    return _page([O.order_admin_view(i, d) for i, d in rows], page, limit)


@router.get("/orders/{order_id}", dependencies=[Depends(require_permission(Perm.ORDERS_VIEW))])
async def admin_get_order(order_id: str, admin: str = Depends(get_current_admin)):
    _check_id(order_id, "order id")
    db = get_db()
    snap = await db.collection(Col.ORDERS).document(order_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    od = snap.to_dict() or {}
    pq = db.collection(Col.PAYMENTS).where(filter=FieldFilter("order_id", "==", order_id)).limit(10)
    payments = []
    async for p in pq.stream():
        pd = p.to_dict() or {}
        payments.append({"id": p.id, **{k: pd.get(k) for k in (
            "payment_method", "verification_method", "verification_status", "expected_usdt", "paid_amount_usdt",
            "currency", "verified_by", "verified_at", "created_at", "attempts", "last_checked_at")}})
    return {**O.order_admin_view(order_id, od), "payments": payments}


@router.get("/transactions", dependencies=[Depends(require_permission(Perm.ORDERS_VIEW))])
async def admin_list_transactions(
    admin: str = Depends(get_current_admin),
    uid: str | None = Query(None, alias="user_id", max_length=128),
    type: str | None = Query(None, max_length=40),
    direction: Literal["credit", "debit"] | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    if uid:
        _check_id(uid, "user id")
    rows = await _scan(db, Col.TRANSACTIONS, eq=("user_id", uid) if uid else None)
    if type:
        rows = [r for r in rows if r[1].get("type") == type]
    if direction:
        rows = [r for r in rows if r[1].get("direction") == direction]
    return _page([O.transaction_admin_view(i, d) for i, d in rows], page, limit)


# ═══ Users ════════════════════════════════════════════════════════════════════
@router.get("/users", dependencies=[Depends(require_permission(Perm.USERS_VIEW))])
async def admin_list_users(
    admin: str = Depends(get_current_admin),
    q: str | None = Query(None, max_length=100),
    banned: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    rows = await _scan(db, Col.USERS)
    if q:
        rows = [r for r in rows if O.matches_user_query(r[0], r[1], q)]
    views = [O.user_admin_view(i, d) for i, d in rows]
    if banned is not None:
        views = [v for v in views if v["is_banned"] is banned]
    return _page(views, page, limit)


@router.get("/users/{uid}", dependencies=[Depends(require_permission(Perm.USERS_VIEW))])
async def admin_get_user(uid: str, admin: str = Depends(get_current_admin)):
    _check_id(uid, "user id")
    db = get_db()
    snap = await db.collection(Col.USERS).document(uid).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="User not found")
    now = _NOW()
    orders = (await _scan(db, Col.ORDERS, eq=("user_id", uid), cap=20))
    txs = (await _scan(db, Col.TRANSACTIONS, eq=("user_id", uid), cap=20))
    ents = [d.to_dict() or {} async for d in
            db.collection(Col.ENTITLEMENTS).where(filter=FieldFilter("user_id", "==", uid)).limit(500).stream()]
    states: dict[str, int] = {}
    for e in ents:
        s = entitlement_state(e, now)
        states[s] = states.get(s, 0) + 1
    return {
        **O.user_admin_view(uid, snap.to_dict() or {}),
        "access_summary": states,
        "recent_orders": [O.order_admin_view(i, d) for i, d in orders],
        "recent_transactions": [O.transaction_admin_view(i, d) for i, d in txs],
    }


# ═══ Support ══════════════════════════════════════════════════════════════════
class TicketReply(BaseModel):
    model_config = {"extra": "forbid"}
    reply: str = Field(min_length=1, max_length=O.TICKET_REPLY_MAX)
    status: Literal["open", "in_progress", "resolved", "closed"] = "resolved"


class TicketStatus(BaseModel):
    model_config = {"extra": "forbid"}
    status: Literal["open", "in_progress", "resolved", "closed"]


@router.get("/support/tickets", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_list_tickets(
    admin: str = Depends(get_current_admin),
    status: Literal["open", "in_progress", "resolved", "closed"] | None = Query(None),
    uid: str | None = Query(None, alias="user_id", max_length=128),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    if uid:
        _check_id(uid, "user id")
    eq = ("user_id", uid) if uid else (("status", status) if status else None)
    rows = await _scan(db, Col.SUPPORT_TICKETS, eq=eq)
    if uid and status:
        rows = [r for r in rows if r[1].get("status") == status]
    return _page([O.ticket_admin_view(i, d) for i, d in rows], page, limit)


async def _load_ticket(db, ticket_id: str):
    _check_id(ticket_id, "ticket id")
    ref = db.collection(Col.SUPPORT_TICKETS).document(ticket_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ref, snap.to_dict() or {}


@router.get("/support/tickets/{ticket_id}", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_get_ticket(ticket_id: str, admin: str = Depends(get_current_admin)):
    _, t = await _load_ticket(get_db(), ticket_id)
    return O.ticket_admin_view(ticket_id, t)


@router.post("/support/tickets/{ticket_id}/reply", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_reply_ticket(ticket_id: str, body: TicketReply, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref, t = await _load_ticket(db, ticket_id)
    now = _NOW()
    changes = {**O.ticket_status_changes(body.status, now, admin),
               "admin_reply": body.reply.strip(), "replied_by": admin, "replied_at": now}
    await ref.update(changes)
    if t.get("user_id"):
        await create_notification(str(t["user_id"]), "system", "Support reply",
                                  body.reply.strip()[:500])
    await audit_log(action="ticket_replied", performed_by=admin, target_type="support_ticket", target_id=ticket_id,
                    before={"status": t.get("status")}, after={"status": body.status, "user_id": t.get("user_id")})
    return O.ticket_admin_view(ticket_id, {**t, **changes})


@router.patch("/support/tickets/{ticket_id}/status", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_set_ticket_status(ticket_id: str, body: TicketStatus, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref, t = await _load_ticket(db, ticket_id)
    changes = O.ticket_status_changes(body.status, _NOW(), admin)
    await ref.update(changes)
    await audit_log(action="ticket_status_changed", performed_by=admin, target_type="support_ticket", target_id=ticket_id,
                    before={"status": t.get("status")}, after={"status": body.status})
    return O.ticket_admin_view(ticket_id, {**t, **changes})


# ─── FAQ ──────────────────────────────────────────────────────────────────────
class FaqUpsert(BaseModel):
    model_config = {"extra": "forbid"}
    question: str | None = Field(default=None, max_length=300)
    answer: str | None = Field(default=None, max_length=3000)
    display_order: int | None = Field(default=None, ge=0, le=10_000)
    is_visible: bool | None = None


_FAQ_WRITE = ("question", "answer", "display_order", "is_visible")


def _faq_view(faq_id: str, d: dict) -> dict:
    return {"id": faq_id, **{k: d.get(k) for k in (*_FAQ_WRITE, "created_at", "updated_at")}}


@router.get("/faqs", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_list_faqs(admin: str = Depends(get_current_admin)):
    rows = [(d.id, d.to_dict() or {}) async for d in get_db().collection(Col.FAQ).stream()]
    rows.sort(key=lambda r: (r[1].get("display_order") if isinstance(r[1].get("display_order"), int) else 10_000, r[0]))
    return {"items": [_faq_view(i, d) for i, d in rows], "fields": O.FAQ_FIELDS}


@router.post("/faqs", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_create_faq(body: FaqUpsert, admin: str = Depends(get_current_admin)):
    import uuid
    data = {"display_order": 100, "is_visible": True, **{k: v for k, v in _sent(body).items() if v is not None}}
    if problems := O.faq_problems(data):
        _422(problems)
    data["question"], data["answer"] = data["question"].strip(), data["answer"].strip()
    now = _NOW()
    data.update(created_at=now, updated_at=now)
    faq_id = f"faq_{uuid.uuid4().hex[:10]}"
    await get_db().collection(Col.FAQ).document(faq_id).create(data)
    await audit_log(action="faq_created", performed_by=admin, target_type="faq", target_id=faq_id,
                    after={k: data[k] for k in _FAQ_WRITE})
    return _faq_view(faq_id, data)


@router.put("/faqs/{faq_id}", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_update_faq(faq_id: str, body: FaqUpsert, admin: str = Depends(get_current_admin)):
    _check_id(faq_id, "FAQ id")
    ref = get_db().collection(Col.FAQ).document(faq_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="FAQ not found")
    cur = snap.to_dict() or {}
    changes = {k: v for k, v in _sent(body).items() if v is not None}
    merged = {**cur, **changes}
    if problems := O.faq_problems(merged):
        _422(problems)
    for k in ("question", "answer"):
        if k in changes:
            changes[k] = changes[k].strip()
    changes["updated_at"] = _NOW()
    await ref.update(changes)
    await audit_log(action="faq_updated", performed_by=admin, target_type="faq", target_id=faq_id,
                    before={k: cur.get(k) for k in changes if k != "updated_at"},
                    after={k: v for k, v in changes.items() if k != "updated_at"})
    return _faq_view(faq_id, {**cur, **changes})


@router.delete("/faqs/{faq_id}", dependencies=[Depends(require_permission(Perm.SUPPORT_MANAGE))])
async def admin_delete_faq(faq_id: str, admin: str = Depends(get_current_admin)):
    _check_id(faq_id, "FAQ id")
    ref = get_db().collection(Col.FAQ).document(faq_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="FAQ not found")
    cur = snap.to_dict() or {}
    await ref.delete()
    await audit_log(action="faq_deleted", performed_by=admin, target_type="faq", target_id=faq_id,
                    before={k: cur.get(k) for k in ("question", "display_order", "is_visible")})
    return {"id": faq_id, "deleted": True}


# ═══ Audit log ════════════════════════════════════════════════════════════════
@router.get("/audit-logs", dependencies=[Depends(require_permission(Perm.AUDIT_VIEW))])
async def admin_list_audit_logs(
    admin: str = Depends(get_current_admin),
    action: str | None = Query(None, max_length=80),
    performed_by: str | None = Query(None, max_length=64),
    target_type: str | None = Query(None, max_length=60),
    target_id: str | None = Query(None, max_length=200),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
):
    """Newest-first over the latest `AUDIT_SCAN_CAP` entries; snapshots are redacted."""
    rows = await _scan(get_db(), Col.AUDIT_LOGS, cap=O.AUDIT_SCAN_CAP)
    rows = [r for r in rows if O.audit_matches(r[1], action=action, performed_by=performed_by,
                                                target_type=target_type, target_id=target_id,
                                                since=since, until=until)]
    out = _page(rows, page, limit)
    out["items"] = [O.audit_admin_view(i, d) for i, d in out["items"]]
    out["scan_cap"] = O.AUDIT_SCAN_CAP
    return out


# ═══ Categories ═══════════════════════════════════════════════════════════════
class CategoryUpsert(BaseModel):
    model_config = {"extra": "forbid"}
    id: str | None = Field(default=None, max_length=64)           # create only
    name: str | None = Field(default=None, max_length=80)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    display_order: int | None = Field(default=None, ge=0, le=10_000)
    is_visible: bool | None = None


_CAT_WRITE = ("name", "slug", "description", "thumbnail_url", "display_order", "is_visible")


def _category_view(cat_id: str, d: dict) -> dict:
    return {"id": cat_id, **{k: d.get(k) for k in (*_CAT_WRITE, "video_count", "created_at", "updated_at")}}


async def _slug_taken(db, slug: str, except_id: str | None) -> bool:
    async for d in db.collection(Col.CATEGORIES).stream():
        if d.id != except_id and (d.to_dict() or {}).get("slug") == slug:
            return True
    return False


@router.get("/categories", dependencies=[Depends(require_permission(Perm.VIDEOS_VIEW))])
async def admin_list_categories(admin: str = Depends(get_current_admin)):
    rows = [(d.id, d.to_dict() or {}) async for d in get_db().collection(Col.CATEGORIES).stream()]
    rows.sort(key=lambda r: (r[1].get("display_order") if isinstance(r[1].get("display_order"), int) else 10_000, r[0]))
    return {"items": [_category_view(i, d) for i, d in rows]}


@router.get("/categories/{cat_id}", dependencies=[Depends(require_permission(Perm.VIDEOS_VIEW))])
async def admin_get_category(cat_id: str, admin: str = Depends(get_current_admin)):
    _check_id(cat_id, "category id")
    db = get_db()
    snap = await db.collection(Col.CATEGORIES).document(cat_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Category not found")
    live = await _count(db.collection(Col.VIDEOS).where(filter=FieldFilter("category_ids", "array_contains", cat_id))
                        .where(filter=FieldFilter("is_published", "==", True)))
    return {**_category_view(cat_id, snap.to_dict() or {}), "published_video_count": live}


@router.post("/categories", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_create_category(body: CategoryUpsert, admin: str = Depends(get_current_admin)):
    import uuid
    data = {k: v for k, v in _sent(body).items() if k in _CAT_WRITE and v is not None}
    cat_id = body.id or f"cat_{uuid.uuid4().hex[:10]}"
    _check_id(cat_id, "category id")
    if not cfg.ID_RE.match(cat_id):
        raise HTTPException(status_code=422, detail="id must be 2–64 chars: letters, digits, _ or -")
    data["slug"] = body.slug or cfg.slugify(data.get("name", "")) or cat_id.lower()
    for k, spec in O.CATEGORY_FIELDS.items():
        if "default" in spec and k not in data:
            data[k] = spec["default"]
    data.setdefault("description", None)
    data.setdefault("thumbnail_url", "")
    if problems := O.category_problems(data):
        _422(problems)
    db = get_db()
    if await _slug_taken(db, data["slug"], None):
        raise HTTPException(status_code=409, detail="Slug already used by another category")
    now = _NOW()
    data.update(name=data["name"].strip(), video_count=0, created_at=now, updated_at=now)
    try:
        await db.collection(Col.CATEGORIES).document(cat_id).create(data)       # never overwrites
    except AlreadyExists:
        raise HTTPException(status_code=409, detail="Category ID already exists")
    await audit_log(action="category_created", performed_by=admin, target_type="category", target_id=cat_id,
                    after={k: data[k] for k in _CAT_WRITE})
    return _category_view(cat_id, data)


@router.put("/categories/{cat_id}", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_update_category(cat_id: str, body: CategoryUpsert, admin: str = Depends(get_current_admin)):
    """Partial update: only fields sent change; the merged result is validated."""
    _check_id(cat_id, "category id")
    if body.id and body.id != cat_id:
        raise HTTPException(status_code=422, detail="Category ID cannot be changed")
    db = get_db()
    ref = db.collection(Col.CATEGORIES).document(cat_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Category not found")
    cur = snap.to_dict() or {}
    changes = {k: v for k, v in _sent(body).items() if k in _CAT_WRITE and v is not None}
    merged = {**cur, **changes}
    if problems := O.category_problems(merged):
        _422(problems)
    if "slug" in changes and await _slug_taken(db, changes["slug"], cat_id):
        raise HTTPException(status_code=409, detail="Slug already used by another category")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    changes["updated_at"] = _NOW()
    await ref.update(changes)
    await audit_log(action="category_updated", performed_by=admin, target_type="category", target_id=cat_id,
                    before={k: cur.get(k) for k in changes if k != "updated_at"},
                    after={k: v for k, v in changes.items() if k != "updated_at"})
    return _category_view(cat_id, {**cur, **changes})


@router.post("/categories/{cat_id}/recount", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_recount_category(cat_id: str, admin: str = Depends(get_current_admin)):
    """Store the real number of published videos in this category (the public app shows `video_count`)."""
    _check_id(cat_id, "category id")
    db = get_db()
    ref = db.collection(Col.CATEGORIES).document(cat_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Category not found")
    n = await _count(db.collection(Col.VIDEOS).where(filter=FieldFilter("category_ids", "array_contains", cat_id))
                     .where(filter=FieldFilter("is_published", "==", True)))
    if n is None:
        raise HTTPException(status_code=503, detail="Could not count videos right now")
    await ref.update({"video_count": n, "updated_at": _NOW()})
    await audit_log(action="category_recounted", performed_by=admin, target_type="category", target_id=cat_id,
                    before={"video_count": (snap.to_dict() or {}).get("video_count")}, after={"video_count": n})
    return {"id": cat_id, "video_count": n}


# ═══ Admin accounts (super admin only) ════════════════════════════════════════
class AdminCreate(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=3, max_length=32)
    role: Literal["super_admin", "admin", "moderator"]
    display_name: str | None = Field(default=None, max_length=60)
    password: str = Field(min_length=O.PASSWORD_MIN_BYTES, max_length=O.PASSWORD_MAX_BYTES)


class AdminUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    role: Literal["super_admin", "admin", "moderator"] | None = None
    display_name: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None


class AdminPassword(BaseModel):
    model_config = {"extra": "forbid"}
    password: str = Field(min_length=O.PASSWORD_MIN_BYTES, max_length=O.PASSWORD_MAX_BYTES)


def _env_super() -> str | None:
    """The bootstrap account counts as a super admin only when it can really log in."""
    name = normalize_username(settings.ADMIN_USERNAME)
    return name if name and settings.ADMIN_PASSWORD_HASH else None


async def _load_admin(db, username: str):
    uname = normalize_username(username)
    if not USERNAME_RE.fullmatch(uname):
        raise HTTPException(status_code=422, detail="Invalid username")
    ref = db.collection(Col.ADMIN_USERS).document(uname)
    snap = await ref.get()
    if not snap.exists:
        if uname == _env_super():
            raise HTTPException(status_code=409, detail="This account is defined by environment variables and cannot be edited here")
        raise HTTPException(status_code=404, detail="Admin not found")
    return uname, ref, snap.to_dict() or {}


async def _other_active_supers(db, exclude: str) -> int:
    n = 0
    async for d in db.collection(Col.ADMIN_USERS).stream():
        r = d.to_dict() or {}
        if d.id != exclude and r.get("role") == SUPER_ADMIN and r.get("is_active") is True:
            n += 1
    env = _env_super()
    if env and env != exclude:
        # an env account shadowed by an active Firestore record is already counted above
        snap = await db.collection(Col.ADMIN_USERS).document(env).get()
        if not snap.exists:
            n += 1
    return n


@router.get("/admins", dependencies=[Depends(require_permission(Perm.ADMINS_MANAGE))])
async def admin_list_admins(admin: str = Depends(get_current_admin)):
    db = get_db()
    rows = [(d.id, d.to_dict() or {}) async for d in db.collection(Col.ADMIN_USERS).stream()]
    items = [O.admin_account_view(i, r) for i, r in sorted(rows)]
    env = _env_super()
    if env and env not in {i for i, _ in rows}:
        items.insert(0, O.admin_account_view(env, {"role": SUPER_ADMIN, "is_active": True, "display_name": "Super Admin"}, "env"))
    return {"items": items, "fields": O.ADMIN_ACCOUNT_FIELDS, "roles": list(ROLES)}


@router.post("/admins", dependencies=[Depends(require_permission(Perm.ADMINS_MANAGE))])
async def admin_create_admin(body: AdminCreate, ctx: AdminContext = Depends(get_admin_context)):
    uname = normalize_username(body.username)
    if not USERNAME_RE.fullmatch(uname):
        raise HTTPException(status_code=422, detail="username must be 3–32 chars: a-z 0-9 . _ - (start with a letter or digit)")
    if uname == _env_super():
        raise HTTPException(status_code=409, detail="This username is reserved for the environment account")
    if problem := O.password_problem(body.password):
        raise HTTPException(status_code=422, detail=problem)
    now = _NOW()
    rec = {
        "password_hash": await asyncio.to_thread(hash_password, body.password),
        "role": body.role, "is_active": True, "display_name": (body.display_name or uname).strip(),
        "token_version": 0, "failed_attempts": 0, "locked_until": None, "last_login_at": None,
        "created_at": now, "updated_at": now, "created_by": ctx.username,
    }
    try:
        await get_db().collection(Col.ADMIN_USERS).document(uname).create(rec)     # never overwrites
    except AlreadyExists:
        raise HTTPException(status_code=409, detail="Username already exists")
    await audit_log(action="admin_created", performed_by=ctx.username, target_type="admin_user", target_id=uname,
                    after={"role": body.role, "display_name": rec["display_name"]})
    return O.admin_account_view(uname, rec)


@router.put("/admins/{username}", dependencies=[Depends(require_permission(Perm.ADMINS_MANAGE))])
async def admin_update_admin(username: str, body: AdminUpdate, ctx: AdminContext = Depends(get_admin_context)):
    """Role / display name / active flag. A role or active change signs the account out immediately."""
    db = get_db()
    uname, ref, rec = await _load_admin(db, username)
    sent = {k: v for k, v in _sent(body).items() if v is not None}
    if not sent:
        raise HTTPException(status_code=422, detail="Nothing to update")
    problem = O.admin_change_problem(
        actor=ctx.username, target=uname, target_role=rec.get("role"), target_active=rec.get("is_active") is True,
        new_role=sent.get("role"), new_active=sent.get("is_active"),
        other_active_super_admins=await _other_active_supers(db, uname),
    )
    if problem:
        raise HTTPException(status_code=409, detail=problem)
    changes: dict = {"updated_at": _NOW()}
    if "display_name" in sent:
        changes["display_name"] = sent["display_name"].strip() or uname
    for k in ("role", "is_active"):
        if k in sent and sent[k] != rec.get(k):
            changes[k] = sent[k]
    if "role" in changes or "is_active" in changes:
        changes["token_version"] = int(rec.get("token_version") or 0) + 1       # sign out existing sessions
    await ref.update(changes)
    shown = {k: v for k, v in changes.items() if k not in ("updated_at", "token_version")}
    await audit_log(action="admin_updated", performed_by=ctx.username, target_type="admin_user", target_id=uname,
                    before={k: rec.get(k) for k in shown}, after=shown)
    return O.admin_account_view(uname, {**rec, **changes})


@router.post("/admins/{username}/password", dependencies=[Depends(require_permission(Perm.ADMINS_MANAGE))])
async def admin_reset_admin_password(username: str, body: AdminPassword, ctx: AdminContext = Depends(get_admin_context)):
    """Set a new password; existing sessions end and any lockout is cleared. The password is never logged."""
    db = get_db()
    uname, ref, rec = await _load_admin(db, username)
    if problem := O.password_problem(body.password):
        raise HTTPException(status_code=422, detail=problem)
    await ref.update({
        "password_hash": await asyncio.to_thread(hash_password, body.password),
        "token_version": int(rec.get("token_version") or 0) + 1,
        "failed_attempts": 0, "locked_until": None, "updated_at": _NOW(),
    })
    await audit_log(action="admin_password_reset", performed_by=ctx.username, target_type="admin_user", target_id=uname)
    return {"username": uname, "password_reset": True}
