"""
Maintenance mode enforcement (Phase 12 / Part 2C).

`app_settings/config.maintenance_mode` was only a UI flag (the Mini App showed a screen); the API
kept accepting new orders. The money path is now blocked server-side too, so a modified client
cannot buy during maintenance. Only operations that START a new purchase / unlock are blocked:
reads, auth, already-paid order verification, provider callbacks and every /admin API keep working
(an admin must be able to turn the flag off, and a payment that is already made must still resolve).
"""
from __future__ import annotations

from typing import Any, Mapping

DEFAULT_MESSAGE = "Service is under maintenance. Please try again later."


def maintenance_active(cfg: Mapping[str, Any] | None) -> bool:
    """Strictly `True` only — a malformed value never locks the store."""
    return bool(cfg) and cfg.get("maintenance_mode") is True


async def ensure_not_in_maintenance(db) -> None:
    from fastapi import HTTPException
    from app.db.firebase import Col
    snap = await db.collection(Col.APP_SETTINGS).document("config").get()
    cfg = snap.to_dict() if snap.exists else None
    if maintenance_active(cfg):
        msg = cfg.get("maintenance_message") if isinstance(cfg.get("maintenance_message"), str) else ""
        raise HTTPException(status_code=503, detail=(msg.strip() or DEFAULT_MESSAGE)[:500])
