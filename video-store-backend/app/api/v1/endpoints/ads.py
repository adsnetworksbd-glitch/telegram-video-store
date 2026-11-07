"""
Ads unlock endpoints.
Security: Access is ONLY granted after S2S callback from Monetag verifies ad completion.
Frontend-only callbacks NEVER grant access.
"""
import hmac
import secrets
import uuid
from datetime import datetime, timezone, timedelta

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.async_transaction import async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.firebase import get_db, Col
from app.schemas import AdSession, AdSessionStartRequest, AdSessionCompleteRequest, AdNetworkConfig
from app.services.ad_config import (
    decide_callback, placement_for, rank_networks, resolve_session_settings, session_status,
)
from app.services.ad_providers import CallbackRejected, get_provider
from app.services.entitlement import create_entitlement, has_any_access
from app.services.maintenance import ensure_not_in_maintenance
from app.services.transaction import record_transaction
from app.utils.audit import audit_log

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ads"])


@router.post("/ads/session/start", response_model=AdSession)
async def start_ad_session(
    body: AdSessionStartRequest,
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    await ensure_not_in_maintenance(db)

    # Already has access?
    if await has_any_access(db, user_id, body.content_type, body.content_id):
        raise HTTPException(status_code=409, detail="Already has active access")

    # Active session already exists?
    now = datetime.now(timezone.utc)
    existing_q = (
        db.collection(Col.AD_SESSIONS)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .where(filter=FieldFilter("content_id", "==", body.content_id))
        .where(filter=FieldFilter("is_complete", "==", False))
    )
    # Check ALL open sessions (an old expired one must not hide a live one).
    for d in [d async for d in existing_q.stream()]:
        s = d.to_dict() or {}
        if s.get("content_type", body.content_type) != body.content_type:
            continue
        if s.get("expires_at") and s["expires_at"] > now:
            raise HTTPException(status_code=409, detail="Active ad session exists")

    # Load content to get ads_required
    col = Col.VIDEOS if body.content_type == "video" else Col.PACKAGES
    content_doc = await db.collection(col).document(body.content_id).get()
    if not content_doc.exists or not (content_doc.to_dict() or {}).get("is_published"):
        raise HTTPException(status_code=404, detail="Content not found")
    content = content_doc.to_dict() or {}

    if not content.get("ads_unlock_enabled"):
        raise HTTPException(status_code=400, detail="Ads unlock not enabled for this content")

    # Pick the network for this placement: lowest priority number first,
    # fallback = next usable network (see app.services.ad_config.rank_networks).
    placement = placement_for(body.content_type)
    net_docs = [(d.id, d.to_dict() or {}) async for d in
                db.collection(Col.AD_NETWORKS).where(filter=FieldFilter("is_enabled", "==", True)).stream()]
    ranked = rank_networks(net_docs, placement)
    if not ranked:
        raise HTTPException(status_code=503, detail="No ad network available")
    network_id, net = ranked[0]
    provider = get_provider(net.get("type"))
    cfg = resolve_session_settings(net, content)
    ads_required = cfg["ads_required"]

    # Create session
    session_id = str(uuid.uuid4())
    server_token = secrets.token_hex(32)
    expires_at = now + timedelta(minutes=cfg["timeout_minutes"])

    await db.collection(Col.AD_SESSIONS).document(session_id).set({
        "user_id": user_id,
        "content_type": body.content_type,
        "content_id": body.content_id,
        "network_id": network_id,
        "provider_id": provider.type,
        "placement": placement,
        "status": "pending",
        "unlock_duration_hours": cfg["unlock_hours"],
        "server_token": server_token,
        "ads_required": ads_required,
        "ads_completed": 0,
        "completed_ad_ids": [],
        "s2s_verified_count": 0,
        "frontend_reported_count": 0,
        "is_complete": False,
        "entitlement_id": None,
        "started_at": now,
        "expires_at": expires_at,
        "completed_at": None,
        "ip_address": None,
        "user_agent": None,
    })

    return AdSession(
        session_id=session_id,
        server_token=server_token,
        ads_required=ads_required,
        ads_completed=0,
        s2s_verified_count=0,
        is_complete=False,
        network_config=AdNetworkConfig(**provider.public_config(network_id, net)),
        expires_at=expires_at,
        entitlement_id=None,
        status="pending",
        placement=placement,
    )


@router.post("/ads/session/complete", response_model=AdSession)
async def check_ad_session(
    body: AdSessionCompleteRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Frontend polls this to check if S2S callback has verified enough ads.
    Never grants access based on frontend report alone.
    """
    db = get_db()
    session_doc = await db.collection(Col.AD_SESSIONS).document(body.session_id).get()
    if not session_doc.exists:
        raise HTTPException(status_code=404, detail="Session not found")

    s = session_doc.to_dict() or {}

    if s.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Validate server token
    if not hmac.compare_digest(str(s.get("server_token", "")).encode(), body.server_token.encode()):
        raise HTTPException(status_code=403, detail="Invalid server token")

    now = datetime.now(timezone.utc)
    # Recovery: the threshold was verified by the provider (grant_pending) but
    # the process stopped before the unlock record was written. Finishing it is
    # idempotent (deterministic entitlement id) and is driven by BACKEND state only.
    if s.get("grant_pending") and not s.get("is_complete"):
        try:
            s.update(await _finalize_grant(db, session_doc.reference, body.session_id, s))
        except Exception:
            logger.exception("Ads grant recovery failed for session %s", body.session_id)
    if not s.get("is_complete") and s.get("expires_at") and s["expires_at"] < now:
        raise HTTPException(status_code=400, detail="Session expired")

    # Load network for config response
    net_doc = await db.collection(Col.AD_NETWORKS).document(s["network_id"]).get()
    net = net_doc.to_dict() if net_doc.exists else {}
    provider = get_provider(net.get("type") or s.get("provider_id") or "monetag")
    cfg = (provider.public_config(s["network_id"], net) if provider
           else {"network_id": s["network_id"], "zone_id": net.get("zone_id"), "type": net.get("type", "monetag")})

    return AdSession(
        session_id=body.session_id,
        server_token=body.server_token,
        ads_required=s["ads_required"],
        ads_completed=s.get("ads_completed", 0),
        s2s_verified_count=s.get("s2s_verified_count", 0),
        is_complete=s.get("is_complete", False),
        network_config=AdNetworkConfig(**cfg),
        expires_at=s["expires_at"],
        entitlement_id=s.get("entitlement_id"),
        status=session_status(s, now),
        placement=s.get("placement"),
    )


@router.get("/webhooks/monetag")
@router.post("/webhooks/monetag")
async def monetag_webhook(request: Request):
    """
    Monetag S2S postback. Monetag calls this with GET (macros in the query
    string; the secret token is part of the URL configured in the Monetag
    dashboard). POST (legacy HMAC) is still accepted. Same flow as
    /webhooks/ads/{provider}.
    """
    return await _handle_provider_callback("monetag", request)


@router.get("/webhooks/ads/{provider_type}")
@router.post("/webhooks/ads/{provider_type}")
async def provider_webhook(provider_type: str, request: Request):
    """
    Generic S2S callback for any registered provider — the ONLY trusted ad
    completion signal. The provider module verifies the callback; nothing the
    browser reports can reach this code path.
    """
    return await _handle_provider_callback(provider_type, request)


@async_transactional
async def _claim_ad(transaction, session_ref, ad_id: str, now: datetime):
    """Atomically count ONE verified ad on the session (idempotent by ad_id)."""
    snap = await session_ref.get(transaction=transaction)
    if not snap.exists:
        return {"status": "ignored", "reason": "session not found"}, None, False
    s = snap.to_dict() or {}
    result, update, grant = decide_callback(s, ad_id, now)
    if update:
        transaction.update(session_ref, update)
    return result, {**s, **(update or {})}, grant


async def _finalize_grant(db, session_ref, session_id: str, s: dict) -> dict:
    """
    Create the unlock for a session whose ad threshold the PROVIDER verified.
    Idempotent: entitlement id is deterministic (ent_ads_<session>), the ledger
    id is deterministic, and the session is only marked complete at the end.
    Never touches any other entitlement (paid / lifetime access stays intact).
    """
    content = s["content_type"]
    content_id = s["content_id"]
    user_id = s["user_id"]

    col = Col.VIDEOS if content == "video" else Col.PACKAGES
    content_doc = await db.collection(col).document(content_id).get()
    content_data = (content_doc.to_dict() or {}) if content_doc.exists else {}
    # Duration is decided by the BACKEND when the session starts (content value,
    # else network default); older sessions fall back to the content value.
    duration_hours = s.get("unlock_duration_hours")
    if duration_hours is None:
        duration_hours = content_data.get("ads_unlock_duration_hours", 24)

    ent_id = f"ent_ads_{session_id}"
    created = True
    try:
        await create_entitlement(
            db=db,
            user_id=user_id,
            content_type=content,
            content_id=content_id,
            access_source="ads_unlock",
            duration_hours=duration_hours,
            ad_session_id=session_id,
            included_video_ids=content_data.get("video_ids", []) if content == "package" else [],
            entitlement_id=ent_id,
        )
    except AlreadyExists:
        created = False  # concurrent / repeated finalize — the unlock already exists

    await record_transaction(
        db=db,
        user_id=user_id,
        type_="ads_unlock",
        amount_bdt=0.0,
        direction="credit",
        reference_type="ad_session",
        reference_id=session_id,
        description=f"{'ভিডিও' if content == 'video' else 'প্যাকেজ'} Ads Unlock",
        tx_id=f"ads_{session_id}",
    )
    if created:
        await audit_log(
            action="ads_unlock_granted",
            performed_by=user_id,
            target_type="ad_session",
            target_id=session_id,
            after={
                "entitlement_id": ent_id,
                "content_type": content,
                "content_id": content_id,
                "provider": s.get("provider_id"),
                "verified_ads": s.get("s2s_verified_count"),
                "duration_hours": duration_hours,
            },
        )

    now = datetime.now(timezone.utc)
    done = {"is_complete": True, "status": "completed", "entitlement_id": ent_id,
            "completed_at": now, "grant_pending": False}
    await session_ref.update({**done, "updated_at": now})
    return done


async def _handle_provider_callback(provider_type: str, request: Request):
    provider = get_provider(provider_type)
    if provider is None or not provider.supports_s2s:
        raise HTTPException(status_code=404, detail="Unknown provider")

    body_bytes = await request.body()
    secret = getattr(settings, provider.secret_setting, "") or ""
    try:
        event = provider.verify_callback(
            secret, request.headers, body_bytes, dict(request.query_params),
        )
    except CallbackRejected as e:
        if e.status == 200:
            return {"status": "ignored", "reason": e.detail}
        # generic message only: never reveal which check failed
        raise HTTPException(status_code=e.status, detail="Invalid callback" if e.status == 403 else e.detail)

    session_id, ad_id = event.session_id, event.ad_id
    # A unique ad/transaction id is mandatory: without it a replayed callback
    # could be counted repeatedly and unlock content.
    if not ad_id:
        return {"status": "ignored", "reason": "no ad_id"}

    db = get_db()
    session_ref = db.collection(Col.AD_SESSIONS).document(session_id)
    session_doc = await session_ref.get()
    if not session_doc.exists:
        return {"status": "ignored", "reason": "session not found"}

    s0 = session_doc.to_dict() or {}
    # The callback must come from the provider the session was created for.
    if (s0.get("provider_id") or "monetag") != provider.type:
        return {"status": "ignored", "reason": "provider mismatch"}
    # Ownership: if the network reports which Telegram user saw the ad, it must
    # be the session owner. Zone: must be the zone of the session's network.
    if event.telegram_id and event.telegram_id != str(s0.get("user_id")):
        logger.warning("Ads callback user mismatch for session %s", session_id)
        return {"status": "ignored", "reason": "user mismatch"}
    if event.zone_id:
        net_doc = await db.collection(Col.AD_NETWORKS).document(s0.get("network_id", "_")).get()
        net_zone = (net_doc.to_dict() or {}).get("zone_id") if net_doc.exists else None
        if net_zone and str(net_zone) != event.zone_id:
            logger.warning("Ads callback zone mismatch for session %s", session_id)
            return {"status": "ignored", "reason": "zone mismatch"}

    now = datetime.now(timezone.utc)
    result, s, grant = await _claim_ad(db.transaction(), session_ref, ad_id, now)
    if grant:
        try:
            await _finalize_grant(db, session_ref, session_id, s or s0)
        except Exception:
            # The counted ad is safe (grant_pending). The next callback or the
            # user's next poll completes the unlock idempotently.
            logger.exception("Ads unlock finalize failed for session %s", session_id)
    return result
