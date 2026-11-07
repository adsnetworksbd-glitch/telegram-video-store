"""Videos and categories API."""
import logging
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import ValidationError

from app.core.deps import get_current_user
from app.core.security import decrypt_url
from app.db.firebase import get_db, Col
from app.schemas import (
    Video, VideoDetail, VideoListResponse, SourceAccess,
    Category, CategoryListResponse, CategoryDetailResponse,
    AccessStatus, AvailableMethods,
)
from app.services.entitlement import check_video_access
from app.services.mappers import build_category
from app.services.source_types import normalize_source_type

logger = logging.getLogger(__name__)

router = APIRouter(tags=["videos"])


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _doc_to_video(doc_id: str, data: dict) -> Video:
    return Video(
        id=doc_id,
        title=data.get("title", ""),
        slug=data.get("slug", doc_id),
        thumbnail_url=data.get("thumbnail_url", ""),
        category_ids=data.get("category_ids", []),
        primary_category_id=data.get("primary_category_id", ""),
        quality=data.get("quality", "HD"),
        duration_seconds=data.get("duration_seconds", 0),
        file_size_mb=data.get("file_size_mb", 0),
        price_bdt=data.get("price_bdt", 0),
        is_free=data.get("is_free", False),
        is_featured=data.get("is_featured", False),
        is_trending=data.get("is_trending", False),
        is_latest=data.get("is_latest", False),
        ads_unlock_enabled=data.get("ads_unlock_enabled", False),
        purchase_enabled=data.get("purchase_enabled", True),
        ads_required=data.get("ads_required", 3),
        ads_unlock_duration_hours=data.get("ads_unlock_duration_hours", 24),
        purchase_duration_hours=data.get("purchase_duration_hours", 0),
        view_count=data.get("view_count", 0),
        purchase_count=data.get("purchase_count", 0),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


def _safe_video(doc_id: str, data: dict) -> Video | None:
    """
    `_doc_to_video` for LIST endpoints: a single malformed document (e.g. an
    admin typed quality "720p") is skipped and logged instead of turning the
    whole list — Home, All Videos, Category, Search — into a 500. Nothing is
    invented for the bad field and the document itself is never modified.
    """
    try:
        return _doc_to_video(doc_id, data)
    except ValidationError as exc:
        bad = sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")})
        logger.warning("Skipping malformed video %s (invalid fields: %s)", doc_id, ", ".join(bad) or "?")
        return None


def _videos_from_docs(docs) -> list[Video]:
    out: list[Video] = []
    for d in docs:
        v = _safe_video(d.id, d.to_dict() or {})
        if v is not None:
            out.append(v)
    return out


# ─── Videos ───────────────────────────────────────────────────────────────────
@router.get("/videos", response_model=VideoListResponse)
async def list_videos(
    category_id: str | None = Query(None),
    sort: str = Query("latest"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    query = db.collection(Col.VIDEOS).where(filter=FieldFilter("is_published", "==", True))

    if category_id:
        query = query.where(filter=FieldFilter("category_ids", "array_contains", category_id))

    if sort == "featured":
        query = query.where(filter=FieldFilter("is_featured", "==", True))
    elif sort == "trending":
        query = query.where(filter=FieldFilter("is_trending", "==", True))

    # Ordering
    order_field = "created_at" if sort in ("latest", "trending", "featured") else "view_count"
    query = query.order_by(order_field, direction="DESCENDING")

    all_docs = [d async for d in query.stream()]
    total = len(all_docs)

    # Simple search filter (Firestore doesn't support full-text)
    if search:
        s = search.lower()
        all_docs = [d for d in all_docs if s in d.to_dict().get("title", "").lower()]
        total = len(all_docs)

    start = (page - 1) * limit
    page_docs = all_docs[start:start + limit]
    videos = _videos_from_docs(page_docs)

    return VideoListResponse(items=videos, total=total, page=page, has_more=start + limit < total)


@router.get("/videos/featured", response_model=dict)
async def featured_videos():
    db = get_db()
    q = (
        db.collection(Col.VIDEOS)
        .where(filter=FieldFilter("is_published", "==", True))
        .where(filter=FieldFilter("is_featured", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(10)
    )
    docs = [d async for d in q.stream()]
    return {"videos": _videos_from_docs(docs)}


@router.get("/videos/trending", response_model=dict)
async def trending_videos():
    db = get_db()
    q = (
        db.collection(Col.VIDEOS)
        .where(filter=FieldFilter("is_published", "==", True))
        .where(filter=FieldFilter("is_trending", "==", True))
        .order_by("view_count", direction="DESCENDING")
        .limit(10)
    )
    docs = [d async for d in q.stream()]
    return {"videos": _videos_from_docs(docs)}


@router.get("/videos/latest", response_model=dict)
async def latest_videos():
    db = get_db()
    q = (
        db.collection(Col.VIDEOS)
        .where(filter=FieldFilter("is_published", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(10)
    )
    docs = [d async for d in q.stream()]
    return {"videos": _videos_from_docs(docs)}


@router.get("/videos/{video_id}", response_model=VideoDetail)
async def get_video(
    video_id: str,
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    doc = await db.collection(Col.VIDEOS).document(video_id).get()
    if not doc.exists or not (doc.to_dict() or {}).get("is_published"):
        raise HTTPException(status_code=404, detail="Video not found")

    data = doc.to_dict() or {}
    video = _safe_video(video_id, data)
    if video is None:
        raise HTTPException(status_code=404, detail="Video unavailable")

    # Increment view_count (fire-and-forget)
    try:
        await db.collection(Col.VIDEOS).document(video_id).update(
            {"view_count": data.get("view_count", 0) + 1}
        )
    except Exception:
        pass

    # Access check
    access = await check_video_access(db, user_id, video_id)
    methods = AvailableMethods(
        ads_unlock=data.get("ads_unlock_enabled", False),
        purchase=data.get("purchase_enabled", True),
        is_free=data.get("is_free", False),
    )

    return VideoDetail(
        **video.model_dump(),
        description=data.get("description", ""),
        source_type=normalize_source_type(data.get("source_type")),
        access=access,
        available_methods=methods,
    )


@router.get("/access/video/{video_id}/source", response_model=SourceAccess)
async def get_video_source(
    video_id: str,
    response: Response,
    backup: bool = False,
    user_id: str = Depends(get_current_user),
):
    """
    Return decrypted source URL only if user has valid access.
    Source URL is never stored unencrypted in Firestore.
    """
    # A protected link must never be kept by a browser / proxy cache.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    db = get_db()
    doc = await db.collection(Col.VIDEOS).document(video_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Video not found")

    data = doc.to_dict() or {}

    # Check access
    access = await check_video_access(db, user_id, video_id)
    if not access.granted:
        raise HTTPException(status_code=403, detail="Access denied")

    # Decrypt URL. `?backup=true` asks for the admin-configured backup source (same access check);
    # without it the response is exactly what it always was.
    if backup:
        encrypted_url = data.get("backup_source_url_encrypted", "")
        if not encrypted_url:
            raise HTTPException(status_code=404, detail="Backup source not configured")
        source_type = normalize_source_type(data.get("backup_source_type") or data.get("source_type"))
    else:
        encrypted_url = data.get("source_url_encrypted", "")
        if not encrypted_url:
            raise HTTPException(status_code=404, detail="Source not configured")
        source_type = normalize_source_type(data.get("source_type"))

    try:
        url = decrypt_url(encrypted_url)
    except Exception:
        raise HTTPException(status_code=500, detail="Source unavailable")

    from app.utils.audit import audit_log
    await audit_log(
        action="source_accessed",
        performed_by=user_id,
        target_type="video",
        target_id=video_id,
        after={"access_source": access.source, "is_lifetime": access.is_lifetime, **({"backup": True} if backup else {})},
    )

    return SourceAccess(source_type=source_type, redirect_url=url)


# ─── Categories ───────────────────────────────────────────────────────────────
@router.get("/categories", response_model=CategoryListResponse)
async def list_categories():
    db = get_db()
    q = (
        db.collection(Col.CATEGORIES)
        .where(filter=FieldFilter("is_visible", "==", True))
        .order_by("display_order")
    )
    docs = [d async for d in q.stream()]
    cats = [build_category(d.id, d.to_dict()) for d in docs]
    return CategoryListResponse(categories=cats)


@router.get("/categories/{cat_id}", response_model=CategoryDetailResponse)
async def get_category(cat_id: str):
    db = get_db()
    doc = await db.collection(Col.CATEGORIES).document(cat_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Category not found")
    data = doc.to_dict() or {}
    cat = build_category(cat_id, data)

    q = (
        db.collection(Col.VIDEOS)
        .where(filter=FieldFilter("is_published", "==", True))
        .where(filter=FieldFilter("category_ids", "array_contains", cat_id))
        .order_by("created_at", direction="DESCENDING")
        .limit(20)
    )
    video_docs = [d async for d in q.stream()]
    videos = _videos_from_docs(video_docs)
    return CategoryDetailResponse(category=cat, videos=videos, total=len(videos))


@router.get("/categories/{cat_id}/videos", response_model=VideoListResponse)
async def category_videos(
    cat_id: str,
    sort: str = Query("latest"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    db = get_db()
    order_field = "created_at" if sort == "latest" else "view_count"
    q = (
        db.collection(Col.VIDEOS)
        .where(filter=FieldFilter("is_published", "==", True))
        .where(filter=FieldFilter("category_ids", "array_contains", cat_id))
        .order_by(order_field, direction="DESCENDING")
    )
    all_docs = [d async for d in q.stream()]
    total = len(all_docs)
    start = (page - 1) * limit
    page_docs = all_docs[start:start + limit]
    videos = _videos_from_docs(page_docs)
    return VideoListResponse(items=videos, total=total, page=page, has_more=start + limit < total)
