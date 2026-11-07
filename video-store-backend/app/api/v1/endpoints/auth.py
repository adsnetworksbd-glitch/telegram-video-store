"""Auth endpoints — Telegram initData → JWT."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

from app.core.security import (
    TelegramAuthConfigError,
    create_access_token,
    verify_telegram_init_data,
)
from app.db.firebase import get_db, Col
from app.schemas import TelegramAuthRequest, TokenResponse, UserProfile
from app.services.referral import process_referral_on_register
from app.services.user_auth import find_or_create_user, is_blocked, record_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# One fixed message for every verification failure: the client must not learn
# whether the hash, the date or the payload was wrong (log has the real reason).
_AUTH_FAILED = "Authentication failed"


def _verified_telegram_user(init_data: str) -> dict:
    """Verify initData server-side; the returned user is the ONLY identity source."""
    try:
        return verify_telegram_init_data(init_data)
    except TelegramAuthConfigError:
        logger.error("Telegram auth unavailable: TELEGRAM_BOT_TOKEN is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication unavailable",
        )
    except ValueError as e:
        # Reason code only (never the initData itself, never the token).
        logger.warning("Telegram auth rejected: %s", getattr(e, "reason", "invalid"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTH_FAILED,
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/telegram", response_model=TokenResponse)
async def telegram_login(body: TelegramAuthRequest, request: Request):
    """
    Verify Telegram initData and return JWT.
    Creates the user document on first login; never recreates/resets an existing one.
    """
    tg_user = _verified_telegram_user(body.init_data)
    if not tg_user.get("start_param") and body.start_param:
        # web_app-button launches carry the referral code in the URL, not in initData
        tg_user = {**tg_user, "start_param": body.start_param}
    user_id = str(tg_user["id"])
    db = get_db()
    now = datetime.now(timezone.utc)

    user_data, created = await find_or_create_user(db, tg_user, now)

    if is_blocked(user_data):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account banned")

    if created:
        referred_by = user_data.get("referred_by_code")
        if referred_by:
            await process_referral_on_register(db, user_id, referred_by)
    else:
        user_data = {**user_data, **await record_login(db, user_id, now)}

    token = create_access_token(user_id)

    profile = UserProfile(
        telegram_id=user_id,
        username=user_data.get("username"),
        first_name=user_data.get("first_name", ""),
        last_name=user_data.get("last_name"),
        photo_url=user_data.get("photo_url"),
        referral_code=user_data.get("referral_code", ""),
        referral_count=user_data.get("referral_count", 0),
        referral_reward_total_bdt=user_data.get("referral_reward_total_bdt", 0.0),
        total_spent_bdt=user_data.get("total_spent_bdt", 0.0),
        wallet_balance=0.0,
        wallet_enabled=False,
        is_banned=bool(user_data.get("is_banned", False)),
        created_at=user_data.get("created_at", now),
        last_seen_at=now,
    )
    return TokenResponse(access_token=token, user=profile)


@router.post("/refresh", response_model=dict)
async def refresh_token(body: TelegramAuthRequest):
    """Re-verify initData and return fresh token."""
    tg_user = _verified_telegram_user(body.init_data)

    user_id = str(tg_user["id"])
    db = get_db()
    doc = await db.collection(Col.USERS).document(user_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    if is_blocked(doc.to_dict() or {}):
        raise HTTPException(status_code=403, detail="Account banned")

    await db.collection(Col.USERS).document(user_id).update({
        "last_seen_at": datetime.now(timezone.utc)
    })
    return {"access_token": create_access_token(user_id)}
