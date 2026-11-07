"""
Entitlement Service — single source of truth for access checks.
All access decisions go through check_video_access().
Never trust frontend claims about access.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal
import uuid
import logging

from google.cloud.firestore_v1 import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.db.firebase import Col
from app.schemas import AccessStatus, AccessSource
from app.services.access_rules import evaluate_access
from app.utils.audit import audit_log, create_notification

logger = logging.getLogger(__name__)


async def check_video_access(
    db: AsyncClient,
    user_id: str,
    video_id: str,
) -> AccessStatus:
    """
    Check if user has any valid access to a video.
    Sources: free video, direct entitlement (ads unlock / individual purchase),
    package entitlement. Each entitlement is its own record and is judged on its
    own (see app.services.access_rules); the best valid one is returned and all
    valid sources are listed in `active_sources`.
    `user_id` must come from the verified JWT (Depends(get_current_user)).
    """
    now = datetime.now(timezone.utc)

    # 1. Free video — only while the video is published (a hidden video is not
    #    "free for everyone"; holders of a real entitlement are unaffected).
    video_doc = await db.collection(Col.VIDEOS).document(video_id).get()
    if video_doc.exists:
        v = video_doc.to_dict() or {}
        if v.get("is_free") and v.get("is_published"):
            return AccessStatus(**evaluate_access([], now, is_free=True))

    # 2. Direct video entitlement
    direct_query = (
        db.collection(Col.ENTITLEMENTS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .where(filter=FieldFilter("content_type", "==", "video"))
        .where(filter=FieldFilter("content_id", "==", video_id))
        .where(filter=FieldFilter("status", "==", "active"))
    )
    direct_docs = [d async for d in direct_query.stream()]

    # 3. Package entitlement containing this video
    pkg_query = (
        db.collection(Col.ENTITLEMENTS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .where(filter=FieldFilter("content_type", "==", "package"))
        .where(filter=FieldFilter("included_video_ids", "array_contains", video_id))
        .where(filter=FieldFilter("status", "==", "active"))
    )
    pkg_docs = [d async for d in pkg_query.stream()]

    return AccessStatus(**evaluate_access(
        [(d.to_dict() or {}) for d in direct_docs + pkg_docs], now,
    ))


async def check_package_access(
    db: AsyncClient,
    user_id: str,
    package_id: str,
) -> AccessStatus:
    now = datetime.now(timezone.utc)
    query = (
        db.collection(Col.ENTITLEMENTS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .where(filter=FieldFilter("content_type", "==", "package"))
        .where(filter=FieldFilter("content_id", "==", package_id))
        .where(filter=FieldFilter("status", "==", "active"))
    )
    docs = [d async for d in query.stream()]
    return AccessStatus(**evaluate_access([(d.to_dict() or {}) for d in docs], now))


async def create_entitlement(
    db: AsyncClient,
    user_id: str,
    content_type: Literal["video", "package"],
    content_id: str,
    access_source: str,
    duration_hours: int,  # 0 = lifetime
    order_id: str | None = None,
    ad_session_id: str | None = None,
    included_video_ids: list[str] | None = None,
    entitlement_id: str | None = None,
) -> str:
    """
    Create a new entitlement document.
    Returns entitlement_id.
    If `entitlement_id` is given the document is created with create() and
    raises google.api_core.exceptions.AlreadyExists on a duplicate — this is
    what makes order fulfillment race-safe (one entitlement per order).
    """
    now = datetime.now(timezone.utc)
    is_lifetime = (duration_hours == 0)
    expires_at = None if is_lifetime else now + timedelta(hours=duration_hours)

    ent_id = entitlement_id or str(uuid.uuid4())
    data = {
        "user_id": user_id,
        "content_type": content_type,
        "content_id": content_id,
        "included_video_ids": included_video_ids or [],
        "access_source": access_source,
        "order_id": order_id,
        "ad_unlock_session_id": ad_session_id,
        "start_at": now,
        "expires_at": expires_at,
        "is_lifetime": is_lifetime,
        "status": "active",
        "revoked_reason": None,
        "created_at": now,
    }
    if entitlement_id:
        await db.collection(Col.ENTITLEMENTS).document(ent_id).create(data)
    else:
        await db.collection(Col.ENTITLEMENTS).document(ent_id).set(data)

    # Audit
    await audit_log(
        action="entitlement_created",
        performed_by=user_id,
        target_type=content_type,
        target_id=content_id,
        after={"entitlement_id": ent_id, "source": access_source},
    )

    # Notification
    await create_notification(
        user_id=user_id,
        type_="purchase_success",
        title="Access পাওয়া গেছে ✅",
        body=f"আপনার {'ভিডিও' if content_type == 'video' else 'প্যাকেজ'}-এ Access দেওয়া হয়েছে।",
        action_type=f"open_{content_type}",
        action_id=content_id,
    )

    logger.info(f"Entitlement {ent_id} created for user {user_id} — {content_type}/{content_id}")
    return ent_id


async def has_any_access(
    db: AsyncClient,
    user_id: str,
    content_type: Literal["video", "package"],
    content_id: str,
) -> bool:
    """Quick check: does user already have active access?"""
    if content_type == "video":
        result = await check_video_access(db, user_id, content_id)
    else:
        result = await check_package_access(db, user_id, content_id)
    return result.granted
