"""
Admin configuration API (Phase 12 / Part 1B) — the backend the future Admin Panel uses.

  GET  /admin/config/schema                 field specs + limits + enums + permissions (admin UI renders from this)
  Videos     GET/POST /admin/videos · GET/PUT /admin/videos/{id} · PATCH /admin/videos/{id}/published
  Packages   GET/POST /admin/packages · GET/PUT /admin/packages/{id} · PATCH /admin/packages/{id}/published
  Ads        GET /admin/ads-config · GET /admin/ad-networks/{id}/verification   (writes: existing PUT /admin/ad-networks/{id})
  Payments   GET /admin/payment-config · GET/PUT /admin/payment-settings         (writes: existing /admin/payment-methods)

Same admin JWT + role permissions as the other admin routes; same Firestore collections
(no new database, no schema change — only fields the public API already reads).
Secrets are never accepted into, or returned from, these routes: a video's source URL is
write-only (stored encrypted), and Binance / ad-callback secrets stay in backend env vars.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.admin_roles import AdminContext, Perm
from app.core.config import settings
from app.core.deps import get_admin_context, get_current_admin, require_permission
from app.core.security import encrypt_url
from app.db.firebase import Col, get_db
from app.services import admin_config as cfg
from app.services.ad_config import PLACEMENTS
from app.services.ad_providers import get_provider, provider_types
from app.utils.audit import audit_log
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter

router = APIRouter(prefix="/admin", tags=["admin-config"])

_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


# ─── Schema ───────────────────────────────────────────────────────────────────
@router.get("/config/schema")
async def admin_config_schema(ctx: AdminContext = Depends(get_admin_context)):
    """Any active admin: modules + field specs; `can_view` / `can_manage` reflect THIS admin's role."""
    return cfg.schema_for(ctx.permissions)


# ─── Shared helpers ───────────────────────────────────────────────────────────
def _check_id(item_id: str) -> None:
    if not cfg.ID_RE.match(item_id):
        raise HTTPException(status_code=422, detail="id must be 2–64 chars: letters, digits, _ or -")


def _changes(body: BaseModel, fields) -> dict:
    """Only fields the client actually sent (partial update); explicit nulls are ignored."""
    return {k: getattr(body, k) for k in fields if k in body.model_fields_set and getattr(body, k) is not None}


def _page(items: list, page: int, limit: int) -> dict:
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": len(items), "page": page, "has_more": start + limit < len(items)}


async def _missing_refs(db, collection: str, ids: list[str]) -> list[str]:
    missing = []
    for i in ids:
        if not (await db.collection(collection).document(i).get()).exists:
            missing.append(i)
    return missing


def _ts_sort_key(d: dict):
    return d.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)


# ═══ Videos ═══════════════════════════════════════════════════════════════════
_VIDEO_WRITE = tuple(k for k in cfg.VIDEO_FIELDS if k not in ("source_url", "backup_source_url", "slug"))


class VideoUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    id: str | None = Field(default=None, description="Create only; auto-generated when omitted")
    title: str | None = Field(default=None, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    category_ids: list[str] | None = Field(default=None, max_length=20)
    primary_category_id: str | None = Field(default=None, max_length=128)
    quality: str | None = Field(default=None, max_length=8)
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)
    file_size_mb: float | None = Field(default=None, ge=0, le=1_000_000)
    price_bdt: float | None = Field(default=None, ge=0, le=10_000_000)
    is_free: bool | None = None
    is_featured: bool | None = None
    is_trending: bool | None = None
    is_latest: bool | None = None
    ads_unlock_enabled: bool | None = None
    purchase_enabled: bool | None = None
    ads_required: int | None = Field(default=None, ge=1, le=50)
    ads_unlock_duration_hours: int | None = Field(default=None, ge=0, le=cfg.MAX_DURATION_HOURS)
    purchase_duration_hours: int | None = Field(default=None, ge=0, le=cfg.MAX_DURATION_HOURS)
    is_published: bool | None = None
    source_type: str | None = Field(default=None, max_length=32)
    source_url: str | None = Field(default=None, max_length=2000)   # write-only
    backup_source_type: str | None = Field(default=None, max_length=32)
    backup_source_url: str | None = Field(default=None, max_length=2000)   # write-only; "" removes it


class PublishedRequest(BaseModel):
    is_published: bool


def _video_view(vid: str, d: dict) -> dict:
    """Admin view: every admin-controlled field + counters. The source URL is never included."""
    out = {"id": vid, **{k: d.get(k) for k in _VIDEO_WRITE}, "slug": d.get("slug") or vid}
    out.update(has_source=bool(d.get("source_url_encrypted")), has_backup_source=bool(d.get("backup_source_url_encrypted")),
               view_count=d.get("view_count", 0),
               purchase_count=d.get("purchase_count", 0), created_at=d.get("created_at"), updated_at=d.get("updated_at"))
    return out


async def _validate_video_refs(db, merged: dict, changes: dict) -> None:
    if "category_ids" in changes:
        missing = await _missing_refs(db, Col.CATEGORIES, changes["category_ids"])
        if missing:
            raise HTTPException(status_code=422, detail=f"Unknown category: {', '.join(missing)}")


def _source_fields(source_url: str) -> dict:
    try:
        return {"source_url_encrypted": encrypt_url(source_url)}
    except Exception:
        raise HTTPException(status_code=503, detail="Source encryption is not configured on the server")


def _backup_fields(backup_url: str | None) -> dict:
    """None = untouched · "" = remove the backup · https URL = store it encrypted."""
    if backup_url is None:
        return {}
    if backup_url == "":
        return {"backup_source_url_encrypted": None, "backup_source_type": None}
    try:
        return {"backup_source_url_encrypted": encrypt_url(backup_url)}
    except Exception:
        raise HTTPException(status_code=503, detail="Source encryption is not configured on the server")


@router.get("/videos", dependencies=[Depends(require_permission(Perm.VIDEOS_VIEW))])
async def admin_list_videos(
    admin: str = Depends(get_current_admin),
    q: str | None = Query(None, max_length=100),
    published: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    rows = [(d.id, d.to_dict() or {}) async for d in db.collection(Col.VIDEOS).stream()]
    if published is not None:
        rows = [r for r in rows if bool(r[1].get("is_published")) is published]
    if q:
        s = q.lower()
        rows = [r for r in rows if s in str(r[1].get("title", "")).lower() or s in r[0].lower()]
    rows.sort(key=lambda r: _ts_sort_key(r[1]), reverse=True)
    return _page([_video_view(i, d) for i, d in rows], page, limit)


@router.get("/videos/{video_id}", dependencies=[Depends(require_permission(Perm.VIDEOS_VIEW))])
async def admin_get_video(video_id: str, admin: str = Depends(get_current_admin)):
    db = get_db()
    snap = await db.collection(Col.VIDEOS).document(video_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Video not found")
    pq = db.collection(Col.PACKAGES).where(filter=FieldFilter("video_ids", "array_contains", video_id))
    pkgs = [{"id": p.id, "name": (p.to_dict() or {}).get("name"), "is_published": bool((p.to_dict() or {}).get("is_published"))}
            async for p in pq.stream()]
    return {**_video_view(video_id, snap.to_dict() or {}), "packages": pkgs}


@router.post("/videos", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_create_video(body: VideoUpsert, admin: str = Depends(get_current_admin)):
    import uuid
    data = _changes(body, _VIDEO_WRITE)
    video_id = body.id or f"vid_{uuid.uuid4().hex[:10]}"
    _check_id(video_id)
    data["slug"] = body.slug or cfg.slugify(data.get("title", "")) or video_id
    src = body.source_url
    backup = body.backup_source_url or None
    problems = cfg.video_problems({**data, "source_url": src, "has_source": bool(src), "backup_source_url": backup}, creating=True)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    db = get_db()
    await _validate_video_refs(db, data, data)
    # Defaults come from the field specs (backend constants), never from the client app.
    for k, spec in cfg.VIDEO_FIELDS.items():
        if "default" in spec and k not in data and k not in ("source_url", "backup_source_url"):
            data[k] = spec["default"]
    if src:
        data.update(_source_fields(src))
    if backup:
        data.update(_backup_fields(backup))
    now = _NOW()
    data.update(view_count=0, purchase_count=0, created_at=now, updated_at=now)
    try:
        await db.collection(Col.VIDEOS).document(video_id).create(data)    # never overwrites
    except AlreadyExists:
        raise HTTPException(status_code=409, detail="Video ID already exists")
    await audit_log(action="video_created", performed_by=admin, target_type="video", target_id=video_id,
                    after={k: v for k, v in data.items() if k not in ("source_url_encrypted", "backup_source_url_encrypted", "created_at", "updated_at")})
    return _video_view(video_id, data)


@router.put("/videos/{video_id}", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_update_video(video_id: str, body: VideoUpsert, admin: str = Depends(get_current_admin)):
    """Partial update: only fields sent change; the merged result is validated."""
    if body.id and body.id != video_id:
        raise HTTPException(status_code=422, detail="Video ID cannot be changed")
    db = get_db()
    ref = db.collection(Col.VIDEOS).document(video_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Video not found")
    before = snap.to_dict() or {}
    changes = _changes(body, (*_VIDEO_WRITE, "slug"))
    merged = {**before, **changes}
    has_source = bool(before.get("source_url_encrypted")) or bool(body.source_url)
    problems = cfg.video_problems({**merged, "source_url": body.source_url, "has_source": has_source,
                                   "backup_source_url": body.backup_source_url or None})
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    await _validate_video_refs(db, merged, changes)
    if body.source_url:
        changes.update(_source_fields(body.source_url))
    changes.update(_backup_fields(body.backup_source_url))
    changes["updated_at"] = _NOW()
    await ref.update(changes)
    safe = lambda dct: {k: v for k, v in dct.items() if k not in ("source_url_encrypted", "backup_source_url_encrypted", "updated_at")}  # noqa: E731
    await audit_log(action="video_updated", performed_by=admin, target_type="video", target_id=video_id,
                    before={k: before.get(k) for k in safe(changes) if k in before}, after=safe(changes))
    return _video_view(video_id, {**merged, **changes})


@router.patch("/videos/{video_id}/published", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_set_video_published(video_id: str, body: PublishedRequest, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref = db.collection(Col.VIDEOS).document(video_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Video not found")
    before = snap.to_dict() or {}
    merged = {**before, "is_published": body.is_published}
    if body.is_published:
        problems = cfg.video_problems({**merged, "has_source": bool(before.get("source_url_encrypted"))})
        if problems:
            raise HTTPException(status_code=422, detail="; ".join(problems))
    await ref.update({"is_published": body.is_published, "updated_at": _NOW()})
    await audit_log(action="video_published" if body.is_published else "video_unpublished", performed_by=admin,
                    target_type="video", target_id=video_id,
                    before={"is_published": bool(before.get("is_published"))}, after={"is_published": body.is_published})
    return _video_view(video_id, merged)


# ═══ Packages ═════════════════════════════════════════════════════════════════
_PACKAGE_WRITE = tuple(cfg.PACKAGE_FIELDS)


class PackageUpsert(BaseModel):
    model_config = {"extra": "forbid"}

    id: str | None = Field(default=None, description="Create only; auto-generated when omitted")
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    video_ids: list[str] | None = Field(default=None, max_length=cfg.MAX_PACKAGE_VIDEOS)
    price_bdt: float | None = Field(default=None, ge=0, le=10_000_000)
    original_price_bdt: float | None = Field(default=None, ge=0, le=10_000_000)
    ads_unlock_enabled: bool | None = None
    purchase_enabled: bool | None = None
    duration_type: str | None = Field(default=None, max_length=16)
    duration_hours: int | None = Field(default=None, ge=0, le=cfg.MAX_DURATION_HOURS)
    ads_required: int | None = Field(default=None, ge=1, le=50)
    is_featured: bool | None = None
    is_published: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=10_000)


def _package_view(pid: str, d: dict) -> dict:
    out = {"id": pid, **{k: d.get(k) for k in _PACKAGE_WRITE}}
    ids = d.get("video_ids") or []
    out.update(video_ids=ids, video_count=len(ids), discount_percentage=d.get("discount_percentage", 0),
               purchase_count=d.get("purchase_count", 0), created_at=d.get("created_at"), updated_at=d.get("updated_at"))
    return out


async def _package_videos(db, ids: list[str]) -> list[dict]:
    """Relationship detail for the admin UI: each included video's state."""
    out = []
    for vid in ids:
        s = await db.collection(Col.VIDEOS).document(vid).get()
        v = (s.to_dict() or {}) if s.exists else {}
        out.append({"id": vid, "exists": s.exists, "title": v.get("title"), "is_published": bool(v.get("is_published"))})
    return out


@router.get("/packages", dependencies=[Depends(require_permission(Perm.VIDEOS_VIEW))])
async def admin_list_packages(
    admin: str = Depends(get_current_admin),
    published: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    rows = [(d.id, d.to_dict() or {}) async for d in db.collection(Col.PACKAGES).stream()]
    if published is not None:
        rows = [r for r in rows if bool(r[1].get("is_published")) is published]
    rows.sort(key=lambda r: (r[1].get("display_order", 100), r[0]))
    return _page([_package_view(i, d) for i, d in rows], page, limit)


@router.get("/packages/{package_id}", dependencies=[Depends(require_permission(Perm.VIDEOS_VIEW))])
async def admin_get_package(package_id: str, admin: str = Depends(get_current_admin)):
    db = get_db()
    snap = await db.collection(Col.PACKAGES).document(package_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Package not found")
    d = snap.to_dict() or {}
    return {**_package_view(package_id, d), "videos": await _package_videos(db, d.get("video_ids") or [])}


async def _check_package(db, merged: dict, changes: dict) -> None:
    problems = cfg.package_problems(merged)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    if "video_ids" in changes:
        missing = await _missing_refs(db, Col.VIDEOS, changes["video_ids"])
        if missing:
            raise HTTPException(status_code=422, detail=f"Unknown video: {', '.join(missing)}")


@router.post("/packages", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_create_package(body: PackageUpsert, admin: str = Depends(get_current_admin)):
    import uuid
    data = _changes(body, _PACKAGE_WRITE)
    package_id = body.id or f"pkg_{uuid.uuid4().hex[:10]}"
    _check_id(package_id)
    for k, spec in cfg.PACKAGE_FIELDS.items():
        if "default" in spec and k not in data:
            data[k] = spec["default"]
    data.setdefault("video_ids", [])
    data.setdefault("duration_type", "lifetime")
    data.setdefault("purchase_enabled", True)
    if "original_price_bdt" not in data and "price_bdt" in data:
        data["original_price_bdt"] = data["price_bdt"]
    db = get_db()
    await _check_package(db, data, data)
    data.update(cfg.package_derived(data))
    now = _NOW()
    data.update(purchase_count=0, created_at=now, updated_at=now)
    try:
        await db.collection(Col.PACKAGES).document(package_id).create(data)
    except AlreadyExists:
        raise HTTPException(status_code=409, detail="Package ID already exists")
    await audit_log(action="package_created", performed_by=admin, target_type="package", target_id=package_id,
                    after={k: v for k, v in data.items() if k not in ("created_at", "updated_at")})
    return _package_view(package_id, data)


@router.put("/packages/{package_id}", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_update_package(package_id: str, body: PackageUpsert, admin: str = Depends(get_current_admin)):
    if body.id and body.id != package_id:
        raise HTTPException(status_code=422, detail="Package ID cannot be changed")
    db = get_db()
    ref = db.collection(Col.PACKAGES).document(package_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Package not found")
    before = snap.to_dict() or {}
    changes = _changes(body, _PACKAGE_WRITE)
    merged = {**before, **changes}
    await _check_package(db, merged, changes)
    changes.update(cfg.package_derived(merged))
    changes["updated_at"] = _NOW()
    await ref.update(changes)
    await audit_log(action="package_updated", performed_by=admin, target_type="package", target_id=package_id,
                    before={k: before.get(k) for k in changes if k != "updated_at" and k in before},
                    after={k: v for k, v in changes.items() if k != "updated_at"})
    return _package_view(package_id, {**merged, **changes})


@router.patch("/packages/{package_id}/published", dependencies=[Depends(require_permission(Perm.VIDEOS_MANAGE))])
async def admin_set_package_published(package_id: str, body: PublishedRequest, admin: str = Depends(get_current_admin)):
    db = get_db()
    ref = db.collection(Col.PACKAGES).document(package_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Package not found")
    before = snap.to_dict() or {}
    merged = {**before, "is_published": body.is_published}
    if body.is_published:
        problems = cfg.package_problems(merged)
        if problems:
            raise HTTPException(status_code=422, detail="; ".join(problems))
    await ref.update({"is_published": body.is_published, "updated_at": _NOW()})
    await audit_log(action="package_published" if body.is_published else "package_unpublished", performed_by=admin,
                    target_type="package", target_id=package_id,
                    before={"is_published": bool(before.get("is_published"))}, after={"is_published": body.is_published})
    return _package_view(package_id, merged)


# ═══ Ads: overview + verification readiness ═══════════════════════════════════
def _secret_present(provider) -> bool:
    return bool(provider and provider.secret_setting and getattr(settings, provider.secret_setting, ""))


@router.get("/ads-config", dependencies=[Depends(require_permission(Perm.ADS_MANAGE))])
async def admin_ads_config(admin: str = Depends(get_current_admin)):
    """
    Networks in fallback order with their readiness, per placement. Edit a network with
    PUT /admin/ad-networks/{id}. Readiness = configuration only; an ad counts only after
    a real provider callback (S2S) — nothing here marks an ad as verified.
    """
    db = get_db()
    nets = [(d.id, d.to_dict() or {}) async for d in db.collection(Col.AD_NETWORKS).stream()]
    nets.sort(key=lambda t: (t[1].get("priority") if isinstance(t[1].get("priority"), int) else 1000, t[0]))
    rows = [cfg.ad_network_readiness(i, n, _secret_present(get_provider(n.get("type")))) | {"name": n.get("name")}
            for i, n in nets]
    order = {pl: [r["id"] for r in rows if r["placements"].get(pl)] for pl in PLACEMENTS}
    return {"networks": rows, "fallback_order": order, "placements": list(PLACEMENTS), "providers": provider_types()}


@router.get("/ad-networks/{network_id}/verification", dependencies=[Depends(require_permission(Perm.ADS_MANAGE))])
async def admin_ad_network_verification(network_id: str, admin: str = Depends(get_current_admin)):
    db = get_db()
    snap = await db.collection(Col.AD_NETWORKS).document(network_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Network not found")
    n = snap.to_dict() or {}
    return cfg.ad_network_readiness(network_id, n, _secret_present(get_provider(n.get("type"))))


# ═══ Payments: overview + verification settings ═══════════════════════════════
class PaymentSettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    payment_verify_min_interval_seconds: int | None = None
    payment_retry_limit_24h: int | None = None


async def _read_config_doc(db) -> dict:
    snap = await db.collection(Col.APP_SETTINGS).document("config").get()
    return (snap.to_dict() or {}) if snap.exists else {}


@router.get("/payment-config", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_payment_config(admin: str = Depends(get_current_admin)):
    """One screen's worth: methods (auto vs manual), Binance credential readiness, verification settings."""
    from app.services.payment_methods import is_payable, normalize_method
    db = get_db()
    methods = []
    async for d in db.collection(Col.PAYMENT_METHODS).stream():
        m = normalize_method(d.id, d.to_dict() or {})
        methods.append({"id": m["id"], "name": m["name"], "type": m["type"], "kind": m["kind"], "is_enabled": m["is_enabled"],
                        "payable": is_payable(m), "display_order": m["display_order"],
                        "verification": "auto" if m["auto_verification_supported"] else "manual",
                        "manual_review_supported": m["manual_review_supported"]})
    methods.sort(key=lambda m: (m["display_order"], m["id"]))
    return {
        "methods": methods,
        "binance": cfg.binance_readiness(settings.BINANCE_PAY_API_KEY, settings.BINANCE_PAY_API_SECRET,
                                         settings.BINANCE_PAY_MERCHANT_ID),
        "settings": cfg.payment_settings_view(await _read_config_doc(db)),
        "settings_fields": cfg.PAYMENT_SETTING_FIELDS,
    }


@router.get("/payment-settings", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_get_payment_settings(admin: str = Depends(get_current_admin)):
    return {"settings": cfg.payment_settings_view(await _read_config_doc(get_db())), "fields": cfg.PAYMENT_SETTING_FIELDS}


@router.put("/payment-settings", dependencies=[Depends(require_permission(Perm.PAYMENT_METHODS_MANAGE))])
async def admin_update_payment_settings(body: PaymentSettingsUpdate, admin: str = Depends(get_current_admin)):
    changes = _changes(body, cfg.PAYMENT_SETTING_BOUNDS)
    if not changes:
        raise HTTPException(status_code=422, detail="No settings sent")
    problems = cfg.payment_setting_problems(changes)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    db = get_db()
    before = cfg.payment_settings_view(await _read_config_doc(db))
    await db.collection(Col.APP_SETTINGS).document("config").set({**changes, "updated_at": _NOW()}, merge=True)
    await audit_log(action="payment_settings_updated", performed_by=admin, target_type="app_settings", target_id="config",
                    before={k: before[k] for k in changes}, after=changes)
    return {"settings": {**before, **changes}}
