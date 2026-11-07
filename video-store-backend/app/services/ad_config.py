"""
Pure ad-network rules (stdlib only): placements, priority/fallback selection,
resolved session settings, session status. No Firestore / FastAPI here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from app.services.ad_providers.registry import get_provider

PLACEMENT_VIDEO_UNLOCK = "video_unlock"
PLACEMENT_PACKAGE_UNLOCK = "package_unlock"
PLACEMENT_REWARDED = "rewarded"
PLACEMENTS = (PLACEMENT_VIDEO_UNLOCK, PLACEMENT_PACKAGE_UNLOCK, PLACEMENT_REWARDED)

DEFAULT_SESSION_TIMEOUT_MINUTES = 30
DEFAULT_ADS_REQUIRED = 3
DEFAULT_UNLOCK_HOURS = 24


def placement_for(content_type: str) -> str:
    """Unlock sessions are tied to content; `rewarded` has no content flow yet."""
    return PLACEMENT_PACKAGE_UNLOCK if content_type == "package" else PLACEMENT_VIDEO_UNLOCK


def _int(v, default: int, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return max(lo, min(hi, int(v)))


def rank_networks(
    networks: Iterable[tuple[str, Mapping]], placement: str
) -> list[tuple[str, Mapping]]:
    """
    Usable networks for `placement`, best first (lowest priority number wins,
    ties by id). A network is usable only if: enabled, a registered provider,
    real S2S verification (provider AND config), placement not switched off,
    and the provider's required fields are present. The tail of the list is the
    fallback order.
    """
    usable: list[tuple[str, Mapping]] = []
    for nid, n in networks:
        if n.get("is_enabled") is not True:
            continue
        provider = get_provider(n.get("type"))
        if provider is None or not provider.supports_s2s or not n.get("s2s_callback_supported"):
            continue
        placements = n.get("placements")
        if isinstance(placements, Mapping) and placements.get(placement) is False:
            continue
        if isinstance(placements, Mapping) and placement not in placements and placements:
            continue  # explicit placement map that does not list it → not offered
        if any(not n.get(f) for f in provider.required_fields):
            continue
        usable.append((nid, n))
    usable.sort(key=lambda t: (_int(t[1].get("priority"), 1000, 0, 10_000), t[0]))
    return usable


def resolve_session_settings(network: Mapping, content: Mapping) -> dict:
    """Content-level values win; the network supplies defaults."""
    ads_required = _int(
        content.get("ads_required"),
        _int(network.get("default_ads_required"), DEFAULT_ADS_REQUIRED, 1, 50), 1, 50,
    )
    # 0 hours == lifetime (existing backend convention, see create_entitlement)
    unlock_hours = _int(
        content.get("ads_unlock_duration_hours"),
        _int(network.get("unlock_duration_hours"), DEFAULT_UNLOCK_HOURS, 0, 24 * 365 * 10),
        0, 24 * 365 * 10,
    )
    timeout_min = _int(network.get("session_timeout_minutes"), DEFAULT_SESSION_TIMEOUT_MINUTES, 1, 240)
    return {"ads_required": ads_required, "unlock_hours": unlock_hours, "timeout_minutes": timeout_min}


def session_status(s: Mapping, now: datetime) -> str:
    """pending | in_progress | completed | expired (derived; never trusts the client)."""
    if s.get("is_complete"):
        return "completed"
    exp = s.get("expires_at")
    if isinstance(exp, datetime) and exp < now:
        return "expired"
    return "in_progress" if _int(s.get("s2s_verified_count"), 0, 0, 10**6) > 0 else "pending"


def decide_callback(s: Mapping, ad_id: str, now: datetime) -> tuple[dict, dict | None, bool]:
    """
    Pure idempotency core for ONE verified provider callback against the stored
    session `s`. Returns (http_result, firestore_update_or_None, grant).
    Runs inside a Firestore transaction, so two simultaneous callbacks cannot
    both observe the same state: the one that crosses the threshold is the only
    one that sees grant=True the first time (later ones see `grant_pending`).
    """
    required = _int(s.get("ads_required"), DEFAULT_ADS_REQUIRED, 1, 50)
    count = _int(s.get("s2s_verified_count"), 0, 0, 10**6)
    if s.get("is_complete"):
        return {"status": "already_complete"}, None, False
    exp = s.get("expires_at")
    if isinstance(exp, datetime) and exp < now and not s.get("grant_pending"):
        return {"status": "ignored", "reason": "session expired"}, {"status": "expired", "updated_at": now}, False
    ids = list(s.get("completed_ad_ids") or [])
    if ad_id in ids:
        return {"status": "duplicate"}, None, bool(s.get("grant_pending"))
    if count >= required:
        # threshold already reached earlier (grant not finished yet): never count more
        return {"status": "already_complete"}, None, True
    count += 1
    update = {
        "s2s_verified_count": count,
        "ads_completed": count,
        "completed_ad_ids": ids + [ad_id],
        "status": "in_progress",
        "updated_at": now,
    }
    grant = count >= required
    if grant:
        update["grant_pending"] = True
    return {"status": "ok"}, update, grant
