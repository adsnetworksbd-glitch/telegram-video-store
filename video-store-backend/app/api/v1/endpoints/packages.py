"""Packages API."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import ValidationError

from app.core.deps import get_current_user
from app.db.firebase import get_db, Col
from app.schemas import Package, PackageDetail, PackageListResponse, AvailableMethods
from app.services.entitlement import check_package_access
from app.api.v1.endpoints.videos import _safe_video

logger = logging.getLogger(__name__)

router = APIRouter(tags=["packages"])


def _doc_to_package(doc_id: str, data: dict) -> Package:
    return Package(
        id=doc_id,
        name=data.get("name", ""),
        thumbnail_url=data.get("thumbnail_url", ""),
        description=data.get("description", ""),
        video_ids=data.get("video_ids", []),
        video_count=data.get("video_count", 0),
        price_bdt=data.get("price_bdt", 0),
        original_price_bdt=data.get("original_price_bdt", data.get("price_bdt", 0)),
        discount_percentage=data.get("discount_percentage", 0),
        ads_unlock_enabled=data.get("ads_unlock_enabled", False),
        purchase_enabled=data.get("purchase_enabled", True),
        duration_type=data.get("duration_type", "lifetime"),
        duration_hours=data.get("duration_hours", 0),
        ads_required=data.get("ads_required", 3),
        is_featured=data.get("is_featured", False),
        purchase_count=data.get("purchase_count", 0),
        created_at=data.get("created_at", datetime.now(timezone.utc)),
    )


def _safe_package(doc_id: str, data: dict) -> Package | None:
    """List-endpoint variant of `_doc_to_package`: skip + log one malformed document."""
    try:
        return _doc_to_package(doc_id, data)
    except ValidationError as exc:
        bad = sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")})
        logger.warning("Skipping malformed package %s (invalid fields: %s)", doc_id, ", ".join(bad) or "?")
        return None


def _packages_from_docs(docs) -> list[Package]:
    out: list[Package] = []
    for d in docs:
        p = _safe_package(d.id, d.to_dict() or {})
        if p is not None:
            out.append(p)
    return out


@router.get("/packages", response_model=PackageListResponse)
async def list_packages(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=50)):
    db = get_db()
    q = (
        db.collection(Col.PACKAGES)
        .where(filter=FieldFilter("is_published", "==", True))
        .order_by("display_order")
    )
    all_docs = [d async for d in q.stream()]
    total = len(all_docs)
    start = (page - 1) * limit
    pkgs = _packages_from_docs(all_docs[start:start + limit])
    return PackageListResponse(items=pkgs, total=total, page=page, has_more=start + limit < total)


@router.get("/packages/featured", response_model=dict)
async def featured_packages():
    db = get_db()
    q = (
        db.collection(Col.PACKAGES)
        .where(filter=FieldFilter("is_published", "==", True))
        .where(filter=FieldFilter("is_featured", "==", True))
        .order_by("display_order")
        .limit(6)
    )
    docs = [d async for d in q.stream()]
    return {"packages": _packages_from_docs(docs)}


@router.get("/packages/{pkg_id}", response_model=PackageDetail)
async def get_package(pkg_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    doc = await db.collection(Col.PACKAGES).document(pkg_id).get()
    if not doc.exists or not (doc.to_dict() or {}).get("is_published"):
        raise HTTPException(status_code=404, detail="Package not found")
    data = doc.to_dict() or {}
    pkg = _safe_package(pkg_id, data)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package unavailable")

    # Load included videos
    video_ids = data.get("video_ids", [])
    included_videos = []
    for vid_id in video_ids[:20]:  # cap at 20
        vdoc = await db.collection(Col.VIDEOS).document(vid_id).get()
        if vdoc.exists:
            v = _safe_video(vdoc.id, vdoc.to_dict() or {})
            if v is not None:
                included_videos.append(v)

    access = await check_package_access(db, user_id, pkg_id)
    methods = AvailableMethods(
        ads_unlock=data.get("ads_unlock_enabled", False),
        purchase=data.get("purchase_enabled", True),
        is_free=False,
    )
    return PackageDetail(
        **pkg.model_dump(),
        included_videos=included_videos,
        access=access,
        available_methods=methods,
    )
