"""
Access rules — the pure decision logic behind every access check.

No FastAPI / Firestore / pydantic imports on purpose: the Backend is the only
authority on access, and keeping the decision a plain function of
(entitlement documents, now) makes it executable in tests without a database.
`app.services.entitlement` loads the documents and calls into this module;
nothing here reads the clock on its own, writes anything, or trusts anything
that came from the frontend.

Rules implemented here
  • Every entitlement is judged on its OWN record: one expired / revoked /
    malformed record never affects another valid record.
  • Lifetime never expires. A temporary entitlement is valid only while
    `expires_at` is in the future; a temporary record WITHOUT `expires_at` is
    malformed and fails CLOSED (not valid).
  • Ads-unlock, individual purchase and package purchase are separate records;
    all valid ones are reported (`active_sources`) and the best one is `source`.
  • "Best" = lifetime, then the latest expiry, then paid over ads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

ACTIVE = "active"
EXPIRED = "expired"
REVOKED = "revoked"

# Lower number = preferred when two valid records are otherwise equal.
_SOURCE_PRIORITY: dict[str, int] = {
    "individual_purchase": 0,
    "package_purchase": 1,
    "admin_grant": 2,
    "ads_unlock": 3,
    "free": 4,
}
_UNKNOWN_PRIORITY = 9


def _aware(dt: Any) -> datetime | None:
    """A datetime in UTC, or None when `dt` is not a datetime at all."""
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def entitlement_state(data: Mapping[str, Any], now: datetime) -> str:
    """
    State of ONE entitlement document at `now`: "active" | "expired" | "revoked".

      stored status != "active"            → "revoked" (anything unknown fails closed)
      is_lifetime is True                   → "active"
      temporary and expires_at > now        → "active"
      temporary and expires_at <= now       → "expired"
      temporary and no usable expires_at    → "expired" (malformed → fail closed)
    """
    if data.get("status", ACTIVE) != ACTIVE:
        return REVOKED
    if data.get("is_lifetime") is True:
        return ACTIVE
    expires_at = _aware(data.get("expires_at"))
    if expires_at is None:
        return EXPIRED
    return ACTIVE if expires_at > _aware(now) else EXPIRED  # type: ignore[operator]


def _rank(data: Mapping[str, Any]) -> tuple:
    """Sort key: bigger = better."""
    lifetime = data.get("is_lifetime") is True
    expires = _aware(data.get("expires_at"))
    ts = expires.timestamp() if (expires is not None and not lifetime) else 0.0
    prio = _SOURCE_PRIORITY.get(str(data.get("access_source")), _UNKNOWN_PRIORITY)
    return (1 if lifetime else 0, ts, -prio)


def evaluate_access(
    entitlements: Iterable[Mapping[str, Any]],
    now: datetime,
    *,
    is_free: bool = False,
) -> dict[str, Any]:
    """
    Decide access from the user's entitlement documents.

    `entitlements` must already be limited to this user and this content (the
    caller's query does that); `is_free` is the content's own free flag.

    Returns a dict that maps 1:1 onto the `AccessStatus` response schema:
    granted, source, expires_at, is_lifetime, expired, active_sources.
    """
    if is_free:
        return {
            "granted": True, "source": "free", "expires_at": None,
            "is_lifetime": True, "expired": False, "active_sources": ["free"],
        }

    valid: list[Mapping[str, Any]] = []
    had_expired = False
    for data in entitlements:
        state = entitlement_state(data, now)
        if state == ACTIVE:
            valid.append(data)
        elif state == EXPIRED:
            had_expired = True

    if not valid:
        return {
            "granted": False, "source": None, "expires_at": None,
            "is_lifetime": False, "expired": had_expired, "active_sources": [],
        }

    ordered = sorted(valid, key=_rank, reverse=True)
    best = ordered[0]
    sources: list[str] = []
    for d in ordered:
        s = d.get("access_source")
        if isinstance(s, str) and s not in sources:
            sources.append(s)

    lifetime = best.get("is_lifetime") is True
    return {
        "granted": True,
        "source": best.get("access_source"),
        "expires_at": None if lifetime else best.get("expires_at"),
        "is_lifetime": lifetime,
        "expired": False,
        "active_sources": sources,
    }
