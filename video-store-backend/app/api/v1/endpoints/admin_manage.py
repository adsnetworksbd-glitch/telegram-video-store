"""
Admin management API (Phase 12 / Part 1C) — coupons, referral rules, homepage, global settings,
notifications, user access & expiry. Same admin JWT / role permissions, same Firestore
collections as the rest of the backend (no new collection, no schema change).

  Coupons        /admin/coupons …                       coupons.manage
  Referral       /admin/referral-settings, /referrals   settings.manage · users.view
  Homepage       /admin/homepage                        settings.manage   (sections, banners, announcement)
  App settings   /admin/app-settings                    settings.manage   (maintenance mode, rate, links…)
  Notifications  /admin/notifications[/send]            notifications.send
  User access    /admin/users/{id}/access, /entitlements/*, /users/{id}/banned   users.view · users.manage
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, Field

from app.core.admin_roles import Perm
from app.core.deps import get_current_admin, require_permission
from app.db.firebase import Col, get_db
from app.services import admin_settings as S
from app.services.mappers import build_app_config
from app.utils.audit import audit_log

router = APIRouter(prefix="/admin", tags=["admin-manage"])

_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
_UID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _422(problems: list[str]):
    raise HTTPException(status_code=422, detail="; ".join(problems))


def _sent(body: BaseModel) -> dict:
    """Fields the client actually sent (explicit nulls kept — they clear nullable settings)."""
    return {k: getattr(body, k) for k in body.model_fields_set}


def _page(items: list, page: int, limit: int) -> dict:
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": len(items), "page": page, "has_more": start + limit < len(items)}


def _min_dt():
    return datetime.min.replace(tzinfo=timezone.utc)


async def _config_doc(db) -> dict:
    snap = await db.collection(Col.APP_SETTINGS).document("config").get()
    return (snap.to_dict() or {}) if snap.exists else {}


async def _save_config(db, changes: dict) -> None:
    await db.collection(Col.APP_SETTINGS).document("config").set({**changes, "updated_at": _NOW()}, merge=True)


async def _require_user(db, uid: str) -> dict:
    if not _UID_RE.match(uid):
        raise HTTPException(status_code=422, detail="Invalid user id")
    snap = await db.collection(Col.USERS).document(uid).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="User not found")
    return snap.to_dict() or {}


# ═══ Coupons ══════════════════════════════════════════════════════════════════
_COUPON_WRITE = tuple(k for k in S.COUPON_FIELDS if k != "code")


class CouponUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    code: str | None = Field(default=None, max_length=32)         # create only
    description: str | None = Field(default=None, max_length=300)
    discount_type: str | None = Field(default=None, max_length=16)
    discount_value: float | None = Field(default=None, gt=0, le=10_000_000)
    max_discount_bdt: float | None = Field(default=None, gt=0)
    min_order_bdt: float | None = Field(default=None, ge=0)
    usage_limit: int | None = Field(default=None, ge=1, le=10_000_000)
    per_user_limit: int | None = Field(default=None, ge=1, le=1000)
    applicable_to: str | None = Field(default=None, max_length=16)
    applicable_ids: list[str] | None = Field(default=None, max_length=S.MAX_COUPON_IDS)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None


class ActiveRequest(BaseModel):
    is_active: bool


def _coupon_view(cid: str, c: dict) -> dict:
    return {"id": cid, "code": c.get("code"), **{k: c.get(k) for k in _COUPON_WRITE},
            "applicable_ids": c.get("applicable_ids") or [], "used_count": c.get("used_count", 0),
            "type": c.get("type"), "created_for_user": c.get("created_for_user"),
            "created_at": c.get("created_at"), "updated_at": c.get("updated_at")}


async def _check_coupon_targets(db, merged: dict) -> None:
    col = {"videos": Col.VIDEOS, "packages": Col.PACKAGES}.get(merged.get("applicable_to"))
    for i in (merged.get("applicable_ids") or []) if col else []:
        if not (await db.collection(col).document(i).get()).exists:
            raise HTTPException(status_code=422, detail=f"Unknown {merged['applicable_to'][:-1]}: {i}")


@router.get("/coupons", dependencies=[Depends(require_permission(Perm.COUPONS_MANAGE))])
async def admin_list_coupons(
    admin: str = Depends(get_current_admin),
    q: str | None = Query(None, max_length=40),
    active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    rows = [(d.id, d.to_dict() or {}) async for d in db.collection(Col.COUPONS).stream()]
    if active is not None:
        rows = [r for r in rows if bool(r[1].get("is_active")) is active]
    if q:
        rows = [r for r in rows if q.upper() in str(r[1].get("code", ""))]
    rows.sort(key=lambda r: r[1].get("created_at") or _min_dt(), reverse=True)
    return _page([_coupon_view(i, c) for i, c in rows], page, limit)


@router.get("/coupons/{coupon_id}", dependencies=[Depends(require_permission(Perm.COUPONS_MANAGE))])
async def admin_get_coupon(coupon_id: str, admin: str = Depends(get_current_admin)):
    db = get_db()
    snap = await db.collection(Col.COUPONS).document(coupon_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return _coupon_view(coupon_id, snap.to_dict() or {})


@router.get("/coupons/{coupon_id}/usage", dependencies=[Depends(require_permission(Perm.COUPONS_MANAGE))])
async def admin_coupon_usage(
    coupon_id: str, admin: str = Depends(get_current_admin),
    page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    q = db.collection(Col.COUPON_USAGE).where(filter=FieldFilter("coupon_id", "==", coupon_id))
    rows = [d.to_dict() or {} async for d in q.stream()]
    rows.sort(key=lambda r: r.get("used_at") or _min_dt(), reverse=True)
    items = [{k: r.get(k) for k in ("user_id", "order_id", "discount_applied_bdt", "used_at")} for r in rows]
    return _page(items, page, limit)


@router.post("/coupons", dependencies=[Depends(require_permission(Perm.COUPONS_MANAGE))])
async def admin_create_coupon(body: CouponUpsert, admin: str = Depends(get_current_admin)):
    data = {k: v for k, v in _sent(body).items() if k in _COUPON_WRITE and v is not None}
    data["code"] = S.normalize_code(body.code)
    for k, spec in S.COUPON_FIELDS.items():
        if "default" in spec and k not in data:
            data[k] = spec["default"]
    data.setdefault("applicable_ids", [])
    problems = S.coupon_problems(data)
    if problems:
        _422(problems)
    db = get_db()
    await _check_coupon_targets(db, data)
    dup = db.collection(Col.COUPONS).where(filter=FieldFilter("code", "==", data["code"])).limit(1)
    if [d async for d in dup.stream()]:
        raise HTTPException(status_code=409, detail="Coupon code already exists")
    cid = str(uuid.uuid4())
    now = _NOW()
    data.update(used_count=0, created_at=now, updated_at=now, type="admin")
    try:
        await db.collection(Col.COUPONS).document(cid).create(data)
    except AlreadyExists:
        raise HTTPException(status_code=409, detail="Coupon ID already exists")
    await audit_log(action="coupon_created", performed_by=admin, target_type="coupon", target_id=cid,
                    after={k: v for k, v in data.items() if k not in ("created_at", "updated_at")})
    return _coupon_view(cid, data)


@router.put("/coupons/{coupon_id}", dependencies=[Depends(require_permission(Perm.COUPONS_MANAGE))])
async def admin_update_coupon(coupon_id: str, body: CouponUpsert, admin: str = Depends(get_current_admin)):
    """Partial update; the merged coupon is validated. The code never changes (usage records reference it)."""
    db = get_db()
    ref = db.collection(Col.COUPONS).document(coupon_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Coupon not found")
    before = snap.to_dict() or {}
    if body.code is not None and S.normalize_code(body.code) != before.get("code"):
        raise HTTPException(status_code=422, detail="Coupon code cannot be changed")
    changes = {k: v for k, v in _sent(body).items() if k in _COUPON_WRITE}
    merged = {**before, **changes}
    problems = S.coupon_problems(merged)
    if problems:
        _422(problems)
    await _check_coupon_targets(db, merged)
    changes["updated_at"] = _NOW()
    await ref.update(changes)
    await audit_log(action="coupon_updated", performed_by=admin, target_type="coupon", target_id=coupon_id,
                    before={k: before.get(k) for k in changes if k != "updated_at"},
                    after={k: v for k, v in changes.items() if k != "updated_at"})
    return _coupon_view(coupon_id, {**merged, **changes})


@router.patch("/coupons/{coupon_id}/active", dependencies=[Depends(require_permission(Perm.COUPONS_MANAGE))])
async def admin_set_coupon_active(coupon_id: str, body: ActiveRequest, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref = db.collection(Col.COUPONS).document(coupon_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Coupon not found")
    before = snap.to_dict() or {}
    if body.is_active:
        problems = S.coupon_problems({**before, "is_active": True})
        if problems:
            _422(problems)
    await ref.update({"is_active": body.is_active, "updated_at": _NOW()})
    await audit_log(action="coupon_activated" if body.is_active else "coupon_deactivated", performed_by=admin,
                    target_type="coupon", target_id=coupon_id,
                    before={"is_active": bool(before.get("is_active"))}, after={"is_active": body.is_active})
    return _coupon_view(coupon_id, {**before, "is_active": body.is_active})


# ═══ Referral ═════════════════════════════════════════════════════════════════
class ReferralSettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    referral_enabled: bool | None = None
    referral_reward_type: str | None = Field(default=None, max_length=16)
    referral_reward_amount: float | None = None
    referral_fraud_cooldown_hours: int | None = None
    referral_coupon_valid_days: int | None = None


@router.get("/referral-settings", dependencies=[Depends(require_permission(Perm.SETTINGS_MANAGE))])
async def admin_get_referral_settings(admin: str = Depends(get_current_admin)):
    return {"settings": S.referral_settings_view(await _config_doc(get_db())), "fields": S.REFERRAL_FIELDS}


@router.put("/referral-settings", dependencies=[Depends(require_permission(Perm.SETTINGS_MANAGE))])
async def admin_update_referral_settings(body: ReferralSettingsUpdate, admin: str = Depends(get_current_admin)):
    changes = {k: v for k, v in _sent(body).items() if v is not None}
    if not changes:
        raise HTTPException(status_code=422, detail="No settings sent")
    problems = S.referral_problems(changes)
    if problems:
        _422(problems)
    db = get_db()
    before = S.referral_settings_view(await _config_doc(db))
    await _save_config(db, changes)
    await audit_log(action="referral_settings_updated", performed_by=admin, target_type="app_settings",
                    target_id="config", before={k: before[k] for k in changes}, after=changes)
    return {"settings": {**before, **changes}}


@router.get("/referrals", dependencies=[Depends(require_permission(Perm.USERS_VIEW))])
async def admin_list_referrals(
    admin: str = Depends(get_current_admin),
    status: Literal["pending", "qualifying", "rewarded", "fraud_detected"] | None = Query(None),
    referrer_id: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    q = db.collection(Col.REFERRALS)
    if status:
        q = q.where(filter=FieldFilter("status", "==", status))
    if referrer_id:
        q = q.where(filter=FieldFilter("referrer_user_id", "==", referrer_id))
    rows = [(d.id, d.to_dict() or {}) async for d in q.stream()]
    rows.sort(key=lambda r: r[1].get("created_at") or _min_dt(), reverse=True)
    keys = ("referrer_user_id", "referred_user_id", "status", "qualifying_order_id", "reward_type",
            "reward_amount_bdt", "reward_coupon_id", "rewarded_at", "created_at")
    return _page([{"id": i, **{k: r.get(k) for k in keys}} for i, r in rows], page, limit)


# ═══ Homepage ═════════════════════════════════════════════════════════════════
class SectionIn(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(max_length=40)
    label: str = Field(min_length=1, max_length=60)
    enabled: bool = True
    order: int | None = Field(default=None, ge=0, le=1000)


class BannerIn(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(max_length=64)
    title: str | None = Field(default=None, max_length=100)
    image_url: str = Field(max_length=1000)
    link_type: str = Field(default="none", max_length=16)
    link_id: str | None = Field(default=None, max_length=128)
    link_url: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    order: int = Field(default=0, ge=0, le=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HomepageUpdate(BaseModel):
    """Each part is replaced as a whole when sent (sections / banners); announcement fields accept null to clear."""
    model_config = {"extra": "forbid"}
    sections: list[SectionIn] | None = Field(default=None, max_length=len(S.HOMEPAGE_SECTION_IDS))
    banners: list[BannerIn] | None = Field(default=None, max_length=S.MAX_BANNERS)
    homepage_announcement: str | None = Field(default=None, max_length=S.ANNOUNCEMENT_MAX)
    homepage_announcement_url: str | None = Field(default=None, max_length=1000)


def _homepage_view(cfg: dict) -> dict:
    secs = [s for s in (cfg.get("homepage_sections") or []) if isinstance(s, dict)]
    secs.sort(key=lambda s: s.get("order", 0) if isinstance(s.get("order"), int) else 0)
    return {"sections": secs, "banners": cfg.get("homepage_banners") or [],
            "homepage_announcement": cfg.get("homepage_announcement"),
            "homepage_announcement_url": cfg.get("homepage_announcement_url"),
            "fields": S.HOMEPAGE_FIELDS}


@router.get("/homepage", dependencies=[Depends(require_permission(Perm.SETTINGS_MANAGE))])
async def admin_get_homepage(admin: str = Depends(get_current_admin)):
    return _homepage_view(await _config_doc(get_db()))


@router.put("/homepage", dependencies=[Depends(require_permission(Perm.SETTINGS_MANAGE))])
async def admin_update_homepage(body: HomepageUpdate, admin: str = Depends(get_current_admin)):
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(status_code=422, detail="Nothing to update")
    db = get_db()
    changes: dict = {}
    problems: list[str] = []
    if "sections" in sent and body.sections is not None:
        raw = [s.model_dump() for s in body.sections]
        problems += S.section_problems(raw)
        changes["homepage_sections"] = S.normalize_sections(raw)
    if "banners" in sent and body.banners is not None:
        raw = [b.model_dump() for b in body.banners]
        problems += S.banner_problems(raw)
        for b in raw:
            col = {"video": Col.VIDEOS, "package": Col.PACKAGES}.get(b["link_type"])
            if col and b.get("link_id") and not (await db.collection(col).document(b["link_id"]).get()).exists:
                problems.append(f"banner {b['id']!r}: {b['link_type']} {b['link_id']!r} does not exist")
        changes["homepage_banners"] = raw
    for k in ("homepage_announcement", "homepage_announcement_url"):
        if k in sent:
            v = (getattr(body, k) or "").strip() or None
            if k.endswith("_url") and v and not v.startswith("https://"):
                problems.append(f"{k} must start with https://")
            changes[k] = v
    if problems:
        _422(problems)
    before = await _config_doc(db)
    await _save_config(db, changes)
    await audit_log(action="homepage_updated", performed_by=admin, target_type="app_settings", target_id="config",
                    before={k: before.get(k) for k in changes}, after=changes)
    return _homepage_view({**before, **changes})


# ═══ Global app settings / maintenance ════════════════════════════════════════
class AppSettingsUpdate(BaseModel):
    """Partial. Nullable settings (logo, links, support username) accept null / '' to clear."""
    model_config = {"extra": "forbid"}
    app_name: str | None = Field(default=None, max_length=60)
    app_logo_url: str | None = Field(default=None, max_length=1000)
    maintenance_mode: bool | None = None
    maintenance_message: str | None = Field(default=None, max_length=500)
    currency_display: str | None = Field(default=None, max_length=10)
    usdt_to_bdt_rate: float | None = None
    wallet_enabled: bool | None = None
    terms_url: str | None = Field(default=None, max_length=1000)
    privacy_url: str | None = Field(default=None, max_length=1000)
    support_url: str | None = Field(default=None, max_length=1000)
    support_username: str | None = Field(default=None, max_length=33)
    telegram_bot_username: str | None = Field(default=None, max_length=33)


def _app_settings_view(cfg: dict) -> dict:
    out = build_app_config(cfg).model_dump()                 # exactly what GET /config serves
    out["telegram_bot_username"] = cfg.get("telegram_bot_username")
    return out


@router.get("/app-settings", dependencies=[Depends(require_permission(Perm.SETTINGS_MANAGE))])
async def admin_get_app_settings(admin: str = Depends(get_current_admin)):
    return {"settings": _app_settings_view(await _config_doc(get_db())), "fields": S.APP_SETTING_FIELDS}


@router.put("/app-settings", dependencies=[Depends(require_permission(Perm.SETTINGS_MANAGE))])
async def admin_update_app_settings(body: AppSettingsUpdate, admin: str = Depends(get_current_admin)):
    sent = _sent(body)
    # null clears only nullable settings; for the rest a null is "not sent"
    changes = {k: v for k, v in sent.items() if v is not None or S.APP_SETTING_FIELDS[k].get("nullable")}
    changes = S.clean_app_settings(changes)
    if not changes:
        raise HTTPException(status_code=422, detail="No settings sent")
    problems = S.app_setting_problems(changes)
    if problems:
        _422(problems)
    db = get_db()
    before = await _config_doc(db)
    await _save_config(db, changes)
    await audit_log(action="app_settings_updated", performed_by=admin, target_type="app_settings", target_id="config",
                    before={k: before.get(k) for k in changes}, after=changes)
    return {"settings": _app_settings_view({**before, **changes})}


# ═══ Notifications ════════════════════════════════════════════════════════════
class NotificationSend(BaseModel):
    model_config = {"extra": "forbid"}
    target: Literal["user", "all"]
    user_id: str | None = Field(default=None, max_length=64)
    type: str = Field(default="announcement", max_length=20)
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=500)
    action_type: str | None = Field(default=None, max_length=20)
    action_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/notifications", dependencies=[Depends(require_permission(Perm.NOTIFICATIONS_SEND))])
async def admin_list_notifications(
    uid: str = Query(..., alias="user_id", min_length=1, max_length=64),
    admin: str = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    """A user's notifications as the admin sees them (read-only)."""
    db = get_db()
    q = (db.collection(Col.NOTIFICATIONS).where(filter=FieldFilter("user_id", "==", uid))
         .order_by("created_at", direction="DESCENDING"))
    rows = [(d.id, d.to_dict() or {}) async for d in q.stream()]
    keys = ("type", "title", "body", "is_read", "action_type", "action_id", "sent_by", "broadcast_id", "created_at")
    return _page([{"id": i, **{k: r.get(k) for k in keys}} for i, r in rows], page, limit)


@router.get("/notifications/config", dependencies=[Depends(require_permission(Perm.NOTIFICATIONS_SEND))])
async def admin_notification_config(admin: str = Depends(get_current_admin)):
    return {"fields": S.NOTIFICATION_FIELDS, "max_broadcast_users": S.MAX_BROADCAST_USERS}


@router.post("/notifications/send", dependencies=[Depends(require_permission(Perm.NOTIFICATIONS_SEND))])
async def admin_send_notification(body: NotificationSend, admin: str = Depends(get_current_admin)):
    n = body.model_dump()
    problems = S.notification_problems(n)
    if problems:
        _422(problems)
    db = get_db()
    col = {"open_video": Col.VIDEOS, "open_package": Col.PACKAGES}.get(body.action_type or "")
    if col and not (await db.collection(col).document(body.action_id).get()).exists:
        raise HTTPException(status_code=422, detail="action_id does not exist")

    broadcast_id = uuid.uuid4().hex[:12]
    now = _NOW()
    if body.target == "user":
        await _require_user(db, body.user_id)
        recipients = [body.user_id]
    else:
        recipients = []
        async for u in db.collection(Col.USERS).select(["is_banned", "account_status"]).stream():
            d = u.to_dict() or {}
            if not (d.get("is_banned") or d.get("account_status") == "banned"):
                recipients.append(u.id)
            if len(recipients) > S.MAX_BROADCAST_USERS:
                raise HTTPException(status_code=422, detail=f"Too many recipients (limit {S.MAX_BROADCAST_USERS}); nothing was sent")
    payload = {"type": body.type, "title": body.title.strip(), "body": body.body.strip(), "is_read": False,
               "action_type": body.action_type, "action_id": body.action_id, "created_at": now,
               "sent_by": admin, "broadcast_id": broadcast_id}
    for i in range(0, len(recipients), 400):                       # Firestore batch limit is 500
        batch = db.batch()
        for uid in recipients[i:i + 400]:
            batch.set(db.collection(Col.NOTIFICATIONS).document(f"bc_{broadcast_id}_{uid}"), {**payload, "user_id": uid})
        await batch.commit()
    await audit_log(action="notification_sent", performed_by=admin, target_type="notification", target_id=broadcast_id,
                    after={"target": body.target, "user_id": body.user_id, "recipients": len(recipients), "type": body.type,
                           "title": payload["title"]})
    return {"broadcast_id": broadcast_id, "recipients": len(recipients)}


# ═══ User access & expiry ═════════════════════════════════════════════════════
class GrantRequest(BaseModel):
    model_config = {"extra": "forbid"}
    user_id: str = Field(min_length=1, max_length=64)
    content_type: Literal["video", "package"]
    content_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    duration_hours: int = Field(ge=0, le=S.MAX_DURATION_HOURS)        # 0 = lifetime


class ExtendRequest(BaseModel):
    model_config = {"extra": "forbid"}
    hours: int | None = Field(default=None, ge=1, le=S.MAX_DURATION_HOURS)
    lifetime: bool = False


class ReasonRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class BanRequest(BaseModel):
    is_banned: bool
    reason: str | None = Field(default=None, max_length=300)


@router.get("/users/{uid}/access", dependencies=[Depends(require_permission(Perm.USERS_VIEW))])
async def admin_user_access(uid: str, admin: str = Depends(get_current_admin)):
    db = get_db()
    u = await _require_user(db, uid)
    now = _NOW()
    q = db.collection(Col.ENTITLEMENTS).where(filter=FieldFilter("user_id", "==", uid))
    items = [S.entitlement_admin_view(d.id, d.to_dict() or {}, now) async for d in q.stream()]
    items.sort(key=lambda e: e.get("start_at") or _min_dt(), reverse=True)
    from app.services.user_auth import is_blocked
    return {"user": {"id": uid, "username": u.get("username"), "first_name": u.get("first_name"),
                     "is_banned": is_blocked(u), "created_at": u.get("created_at")},
            "entitlements": items}


@router.post("/entitlements/grant", dependencies=[Depends(require_permission(Perm.USERS_MANAGE))])
async def admin_grant_access(body: GrantRequest, admin: str = Depends(get_current_admin)):
    from app.services.entitlement import create_entitlement
    db = get_db()
    await _require_user(db, body.user_id)
    col = Col.VIDEOS if body.content_type == "video" else Col.PACKAGES
    snap = await db.collection(col).document(body.content_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"{body.content_type.title()} not found")
    included = list((snap.to_dict() or {}).get("video_ids") or []) if body.content_type == "package" else []
    ent_id = await create_entitlement(
        db, body.user_id, body.content_type, body.content_id, "admin_grant", body.duration_hours,
        included_video_ids=included,
    )
    await db.collection(Col.ENTITLEMENTS).document(ent_id).update({"granted_by": admin})
    await audit_log(action="access_granted", performed_by=admin, target_type="entitlement", target_id=ent_id,
                    after={"user_id": body.user_id, "content_type": body.content_type, "content_id": body.content_id,
                           "duration_hours": body.duration_hours})
    return S.entitlement_admin_view(ent_id, (await db.collection(Col.ENTITLEMENTS).document(ent_id).get()).to_dict() or {}, _NOW())


async def _load_entitlement(db, ent_id: str):
    ref = db.collection(Col.ENTITLEMENTS).document(ent_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Entitlement not found")
    return ref, snap.to_dict() or {}


@router.post("/entitlements/{ent_id}/revoke", dependencies=[Depends(require_permission(Perm.USERS_MANAGE))])
async def admin_revoke_access(ent_id: str, body: ReasonRequest, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref, e = await _load_entitlement(db, ent_id)
    if e.get("status") == "revoked":
        return S.entitlement_admin_view(ent_id, e, _NOW())          # idempotent
    changes = {"status": "revoked", "revoked_reason": (body.reason or "admin_revoked"), "revoked_at": _NOW(), "revoked_by": admin}
    await ref.update(changes)
    await audit_log(action="access_revoked", performed_by=admin, target_type="entitlement", target_id=ent_id,
                    before={"status": e.get("status")}, after={"status": "revoked", "reason": changes["revoked_reason"],
                                                               "user_id": e.get("user_id")})
    return S.entitlement_admin_view(ent_id, {**e, **changes}, _NOW())


@router.post("/entitlements/{ent_id}/extend", dependencies=[Depends(require_permission(Perm.USERS_MANAGE))])
async def admin_extend_access(ent_id: str, body: ExtendRequest, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref, e = await _load_entitlement(db, ent_id)
    now = _NOW()
    try:
        changes = S.extend_expiry(e, now, hours=body.hours, lifetime=body.lifetime)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await ref.update(changes)
    await audit_log(action="access_extended", performed_by=admin, target_type="entitlement", target_id=ent_id,
                    before={"expires_at": e.get("expires_at"), "is_lifetime": e.get("is_lifetime")},
                    after={**changes, "user_id": e.get("user_id")})
    return S.entitlement_admin_view(ent_id, {**e, **changes}, now)


@router.patch("/users/{uid}/banned", dependencies=[Depends(require_permission(Perm.USERS_MANAGE))])
async def admin_set_user_banned(uid: str, body: BanRequest, admin: str = Depends(get_current_admin)):
    """Ban / unban. Effective immediately: every user request re-reads the account (deps.get_current_user)."""
    db = get_db()
    u = await _require_user(db, uid)
    changes = {"is_banned": body.is_banned, "account_status": "banned" if body.is_banned else "active"}
    if body.is_banned:
        changes.update(banned_at=_NOW(), banned_by=admin, ban_reason=body.reason)
    await db.collection(Col.USERS).document(uid).update(changes)
    await audit_log(action="user_banned" if body.is_banned else "user_unbanned", performed_by=admin,
                    target_type="user", target_id=uid,
                    before={"is_banned": bool(u.get("is_banned")), "account_status": u.get("account_status")},
                    after={"is_banned": body.is_banned, "reason": body.reason})
    return {"id": uid, "is_banned": body.is_banned}
