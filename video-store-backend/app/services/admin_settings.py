"""
Admin-controlled settings rules (Phase 12 / Part 1C) — pure Python, stdlib only.

Coupons, referral rules, homepage (sections / banners / announcement), notifications,
global app settings and user access / expiry. Same idea as admin_config.py: ONE place
holds field specs, limits and validation; the admin API validates with it and the
schema endpoint publishes it, so the Admin Panel hardcodes nothing.

Only rules the backend really enforces are exposed. Coupon fields mirror
services/coupon.py; referral keys mirror services/referral.py; expiry follows
services/access_rules.py. No Firestore / network here.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.core.admin_roles import Perm
from app.services.access_rules import ACTIVE, entitlement_state

MAX_DURATION_HOURS = 24 * 365 * 10          # same ceiling as ads / packages; 0 = lifetime


def _f(type_: str, label: str, **kw: Any) -> dict:
    return {"type": type_, "label": label, **kw}


def _aware(dt: Any) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _https(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("https://")


# ═══ Coupons ══════════════════════════════════════════════════════════════════
COUPON_DISCOUNT_TYPES = ("fixed_bdt", "percentage")
COUPON_APPLICABLE_TO = ("all", "videos", "packages")
COUPON_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")
MAX_COUPON_IDS = 100

COUPON_FIELDS: dict[str, dict] = {
    "code": _f("string", "Code", required=True, create_only=True, pattern=COUPON_CODE_RE.pattern,
               help="Upper-case, unique, cannot be changed after creation"),
    "description": _f("text", "Internal note", max=300),
    "discount_type": _f("enum", "Discount type", options=list(COUPON_DISCOUNT_TYPES), required=True),
    "discount_value": _f("number", "Discount value", min_exclusive=0, max=10_000_000, required=True,
                         help="BDT for fixed_bdt, 1–100 for percentage"),
    "max_discount_bdt": _f("number", "Max discount (BDT)", min_exclusive=0, help="percentage coupons only"),
    "min_order_bdt": _f("number", "Minimum order (BDT)", min=0, default=0),
    "usage_limit": _f("int", "Total uses (empty = unlimited)", min=1, max=10_000_000),
    "per_user_limit": _f("int", "Uses per user", min=1, max=1000, default=1),
    "applicable_to": _f("enum", "Applies to", options=list(COUPON_APPLICABLE_TO), default="all"),
    "applicable_ids": _f("ref_list", "Specific videos / packages", max=MAX_COUPON_IDS,
                         help="Required when applicable_to is videos or packages"),
    "valid_from": _f("datetime", "Valid from"),
    "valid_until": _f("datetime", "Valid until"),
    "is_active": _f("bool", "Active", default=False, help="New coupons start inactive"),
}
COUPON_READ_ONLY = ["used_count", "created_at", "updated_at", "type", "created_for_user"]


def normalize_code(raw: Any) -> str:
    """Same normalisation validate_coupon applies to what the user types."""
    return str(raw or "").strip().upper()


def coupon_problems(c: Mapping[str, Any]) -> list[str]:
    p: list[str] = []
    if not COUPON_CODE_RE.match(normalize_code(c.get("code"))):
        p.append("code must be 3–32 chars: A-Z, 0-9, _ or -")
    dt, val = c.get("discount_type"), c.get("discount_value")
    if dt not in COUPON_DISCOUNT_TYPES:
        p.append(f"discount_type must be one of {list(COUPON_DISCOUNT_TYPES)}")
    if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
        p.append("discount_value must be > 0")
    elif dt == "percentage" and val > 100:
        p.append("a percentage discount cannot exceed 100")
    mx = c.get("max_discount_bdt")
    if mx is not None and (dt != "percentage" or mx <= 0):
        p.append("max_discount_bdt applies to percentage coupons only and must be > 0")
    at, ids = c.get("applicable_to", "all"), c.get("applicable_ids") or []
    if at not in COUPON_APPLICABLE_TO:
        p.append(f"applicable_to must be one of {list(COUPON_APPLICABLE_TO)}")
    elif at != "all" and not ids:
        p.append(f"applicable_ids is required when applicable_to is {at}")
    elif at == "all" and ids:
        p.append("applicable_ids must be empty when applicable_to is all")
    if len(ids) != len(set(ids)):
        p.append("applicable_ids contains duplicates")
    vf, vu = _aware(c.get("valid_from")), _aware(c.get("valid_until"))
    if vf and vu and vu <= vf:
        p.append("valid_until must be after valid_from")
    ul = c.get("usage_limit")
    if ul is not None and c.get("used_count", 0) > ul:
        p.append("usage_limit cannot be lower than the times already used")
    return p


# ═══ Referral ═════════════════════════════════════════════════════════════════
REFERRAL_REWARD_TYPES = ("coupon",)     # the only reward referral.py actually issues
REFERRAL_DEFAULTS = {                    # == the fallbacks inside referral.process_referral_on_purchase
    "referral_enabled": False,
    "referral_reward_type": "coupon",
    "referral_reward_amount": 100,
    "referral_fraud_cooldown_hours": 48,
    "referral_coupon_valid_days": 7,
}
REFERRAL_FIELDS: dict[str, dict] = {
    "referral_enabled": _f("bool", "Referral program enabled", default=REFERRAL_DEFAULTS["referral_enabled"]),
    "referral_reward_type": _f("enum", "Reward type", options=list(REFERRAL_REWARD_TYPES),
                               default=REFERRAL_DEFAULTS["referral_reward_type"]),
    "referral_reward_amount": _f("number", "Reward amount (BDT)", min_exclusive=0, max=100_000,
                                 default=REFERRAL_DEFAULTS["referral_reward_amount"]),
    "referral_fraud_cooldown_hours": _f("int", "Referred account must be older than (hours)", min=0, max=24 * 365,
                                        default=REFERRAL_DEFAULTS["referral_fraud_cooldown_hours"]),
    "referral_coupon_valid_days": _f("int", "Reward coupon validity (days)", min=1, max=365,
                                     default=REFERRAL_DEFAULTS["referral_coupon_valid_days"]),
}
REFERRAL_STATUSES = ("pending", "qualifying", "rewarded", "fraud_detected")


def referral_problems(changes: Mapping[str, Any]) -> list[str]:
    p: list[str] = []
    for k, v in changes.items():
        spec = REFERRAL_FIELDS.get(k)
        if spec is None:
            p.append(f"unknown setting {k}")
        elif spec["type"] == "bool":
            if not isinstance(v, bool):
                p.append(f"{k} must be true or false")
        elif spec["type"] == "enum":
            if v not in spec["options"]:
                p.append(f"{k} must be one of {spec['options']}")
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            p.append(f"{k} must be a number")
        elif spec["type"] == "int" and not float(v).is_integer():
            p.append(f"{k} must be a whole number")
        elif ("min" in spec and v < spec["min"]) or ("max" in spec and v > spec["max"]) \
                or ("min_exclusive" in spec and v <= spec["min_exclusive"]):
            p.append(f"{k} is out of range")
    return p


def referral_settings_view(cfg: Mapping[str, Any] | None) -> dict:
    cfg = cfg or {}
    return {k: cfg.get(k, d) if cfg.get(k) is not None else d for k, d in REFERRAL_DEFAULTS.items()}


# ═══ Homepage: sections, banners, announcement ════════════════════════════════
HOMEPAGE_SECTION_IDS = ("featured_banner", "featured_videos", "trending_videos", "latest_videos",
                        "popular_categories", "featured_packages", "all_videos")   # ids Home/index.tsx renders
BANNER_LINK_TYPES = ("none", "video", "package", "url")
MAX_BANNERS = 10
ANNOUNCEMENT_MAX = 300

HOMEPAGE_FIELDS: dict[str, dict] = {
    "sections": _f("list", "Sections (order = display order)", item={
        "id": _f("enum", "Section", options=list(HOMEPAGE_SECTION_IDS), required=True),
        "label": _f("string", "Label", max=60),
        "enabled": _f("bool", "Shown"),
        "order": _f("int", "Order", min=0, max=1000),
    }, max=len(HOMEPAGE_SECTION_IDS)),
    "banners": _f("list", "Banners", max=MAX_BANNERS, item={
        "id": _f("string", "ID", required=True, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
        "title": _f("string", "Title", max=100),
        "image_url": _f("url", "Image URL", https_only=True, required=True, max=1000),
        "link_type": _f("enum", "Link", options=list(BANNER_LINK_TYPES), default="none"),
        "link_id": _f("string", "Video / package ID", max=128),
        "link_url": _f("url", "External URL", https_only=True, max=1000),
        "enabled": _f("bool", "Shown", default=True),
        "order": _f("int", "Order", min=0, max=1000),
        "starts_at": _f("datetime", "Show from"),
        "ends_at": _f("datetime", "Show until"),
    }),
    "homepage_announcement": _f("text", "Announcement", max=ANNOUNCEMENT_MAX, nullable=True),
    "homepage_announcement_url": _f("url", "Announcement link", https_only=True, max=1000, nullable=True),
}
_BANNER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def section_problems(sections: list[Mapping[str, Any]]) -> list[str]:
    p: list[str] = []
    ids = [s.get("id") for s in sections]
    if len(ids) != len(set(ids)):
        p.append("sections contains duplicate ids")
    for s in sections:
        if s.get("id") not in HOMEPAGE_SECTION_IDS:
            p.append(f"unknown section id {s.get('id')!r}")
        if not str(s.get("label") or "").strip():
            p.append(f"section {s.get('id')!r} needs a label")
    return p


def banner_problems(banners: list[Mapping[str, Any]]) -> list[str]:
    p: list[str] = []
    if len(banners) > MAX_BANNERS:
        p.append(f"at most {MAX_BANNERS} banners")
    ids = [b.get("id") for b in banners]
    if len(ids) != len(set(ids)):
        p.append("banners contains duplicate ids")
    for b in banners:
        bid = b.get("id")
        if not _BANNER_ID_RE.match(str(bid or "")):
            p.append("banner id must be 1–64 chars: letters, digits, _ or -")
        if not _https(b.get("image_url")):
            p.append(f"banner {bid!r}: image_url must start with https://")
        lt = b.get("link_type", "none")
        if lt not in BANNER_LINK_TYPES:
            p.append(f"banner {bid!r}: link_type must be one of {list(BANNER_LINK_TYPES)}")
        elif lt in ("video", "package") and not b.get("link_id"):
            p.append(f"banner {bid!r}: link_id is required for a {lt} link")
        elif lt == "url" and not _https(b.get("link_url")):
            p.append(f"banner {bid!r}: link_url must start with https://")
        s, e = _aware(b.get("starts_at")), _aware(b.get("ends_at"))
        if s and e and e <= s:
            p.append(f"banner {bid!r}: ends_at must be after starts_at")
    return p


def normalize_sections(sections: list[Mapping[str, Any]]) -> list[dict]:
    """Stored shape (same as the seed): id, label, enabled, order. Missing order → list position."""
    return [{"id": s["id"], "label": str(s.get("label") or "").strip(),
             "enabled": bool(s.get("enabled", True)),
             "order": int(s["order"]) if s.get("order") is not None else i + 1}
            for i, s in enumerate(sections)]


def active_banners(raw: Any, now: datetime) -> list[dict]:
    """What the PUBLIC homepage config exposes: enabled, inside its window, sorted. Malformed entries are skipped."""
    out: list[dict] = []
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, Mapping) or b.get("enabled") is False or not _https(b.get("image_url")):
            continue
        s, e = _aware(b.get("starts_at")), _aware(b.get("ends_at"))
        if (s and now < s) or (e and now >= e):
            continue
        lt = b.get("link_type") if b.get("link_type") in BANNER_LINK_TYPES else "none"
        order = b.get("order") if isinstance(b.get("order"), int) and not isinstance(b.get("order"), bool) else 0
        out.append({"id": str(b.get("id") or ""), "title": b.get("title") or None, "image_url": b["image_url"],
                    "link_type": lt, "link_id": b.get("link_id") if lt in ("video", "package") else None,
                    "link_url": b.get("link_url") if lt == "url" and _https(b.get("link_url")) else None,
                    "order": order})
    out.sort(key=lambda x: (x["order"], x["id"]))
    return out


# ═══ Global app settings (app_settings/config) ════════════════════════════════
_TG_NAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
APP_SETTING_FIELDS: dict[str, dict] = {
    "app_name": _f("string", "App name", min_len=1, max=60),
    "app_logo_url": _f("url", "Logo URL", https_only=True, max=1000, nullable=True),
    "maintenance_mode": _f("bool", "Maintenance mode",
                           help="Mini App shows the maintenance screen AND the server rejects new orders / ad sessions (503); admin, auth and already-paid order checks keep working"),
    "maintenance_message": _f("text", "Maintenance message", max=500),
    "currency_display": _f("string", "Display currency", min_len=2, max=10),
    "usdt_to_bdt_rate": _f("number", "USDT → BDT rate", min_exclusive=0, max=10_000,
                           help="Used for every NEW order's USDT amount; existing orders keep their rate"),
    "wallet_enabled": _f("bool", "Wallet enabled"),
    "terms_url": _f("url", "Terms URL", https_only=True, max=1000, nullable=True),
    "privacy_url": _f("url", "Privacy URL", https_only=True, max=1000, nullable=True),
    "support_url": _f("url", "Support URL", https_only=True, max=1000, nullable=True),
    "support_username": _f("string", "Support Telegram username", pattern=_TG_NAME_RE.pattern, nullable=True),
    "telegram_bot_username": _f("string", "Bot username", pattern=_TG_NAME_RE.pattern),
}
_APP_URL_KEYS = ("app_logo_url", "terms_url", "privacy_url", "support_url")


def app_setting_problems(changes: Mapping[str, Any]) -> list[str]:
    p: list[str] = []
    for k, v in changes.items():
        spec = APP_SETTING_FIELDS.get(k)
        if spec is None:
            p.append(f"unknown setting {k}")
            continue
        if v is None:
            if not spec.get("nullable"):
                p.append(f"{k} cannot be empty")
            continue
        t = spec["type"]
        if t == "bool":
            if not isinstance(v, bool):
                p.append(f"{k} must be true or false")
        elif t == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= spec["min_exclusive"] or v > spec["max"]:
                p.append(f"{k} must be > {spec['min_exclusive']} and ≤ {spec['max']}")
        else:
            s = str(v).strip()
            if len(s) < spec.get("min_len", 0) or len(s) > spec.get("max", 10_000):
                p.append(f"{k} has an invalid length")
            if k in _APP_URL_KEYS and not _https(s):
                p.append(f"{k} must start with https://")
            if "pattern" in spec and not re.match(spec["pattern"], s.lstrip("@")):
                p.append(f"{k} is not valid")
    return p


def clean_app_settings(changes: Mapping[str, Any]) -> dict:
    """Trim strings; '' → None for nullable fields; a leading @ is dropped from Telegram usernames."""
    out: dict[str, Any] = {}
    for k, v in changes.items():
        if isinstance(v, str):
            v = v.strip()
            if k in ("support_username", "telegram_bot_username"):
                v = v.lstrip("@")
            if v == "" and APP_SETTING_FIELDS.get(k, {}).get("nullable"):
                v = None
        out[k] = v
    return out


# ═══ Notifications ════════════════════════════════════════════════════════════
NOTIFICATION_TYPES = ("announcement", "promo", "system")                  # admin-sendable
NOTIFICATION_ACTIONS = ("open_video", "open_package", "open_order")       # the only ones the Mini App links
NOTIFICATION_TARGETS = ("user", "all")
MAX_BROADCAST_USERS = 5000
NOTIFICATION_FIELDS: dict[str, dict] = {
    "target": _f("enum", "Send to", options=list(NOTIFICATION_TARGETS), required=True),
    "user_id": _f("string", "User ID", max=64, help="Required for target=user"),
    "type": _f("enum", "Type", options=list(NOTIFICATION_TYPES), default="announcement"),
    "title": _f("string", "Title", required=True, max=100),
    "body": _f("text", "Message", required=True, max=500),
    "action_type": _f("enum", "Opens", options=list(NOTIFICATION_ACTIONS)),
    "action_id": _f("string", "Video / package / order ID", max=128),
}


def notification_problems(n: Mapping[str, Any]) -> list[str]:
    p: list[str] = []
    if n.get("target") not in NOTIFICATION_TARGETS:
        p.append(f"target must be one of {list(NOTIFICATION_TARGETS)}")
    if n.get("target") == "user" and not n.get("user_id"):
        p.append("user_id is required when target is user")
    if n.get("target") == "all" and n.get("user_id"):
        p.append("user_id must be empty when target is all")
    if n.get("type", "announcement") not in NOTIFICATION_TYPES:
        p.append(f"type must be one of {list(NOTIFICATION_TYPES)}")
    if not str(n.get("title") or "").strip() or not str(n.get("body") or "").strip():
        p.append("title and body are required")
    at, aid = n.get("action_type"), n.get("action_id")
    if bool(at) != bool(aid):
        p.append("action_type and action_id must be given together")
    elif at and at not in NOTIFICATION_ACTIONS:
        p.append(f"action_type must be one of {list(NOTIFICATION_ACTIONS)}")
    elif at == "open_order":
        p.append("open_order cannot be sent by an admin broadcast")     # an order belongs to one user's payment flow
    return p


# ═══ User access & expiry ═════════════════════════════════════════════════════
ACCESS_CONTENT_TYPES = ("video", "package")
ACCESS_FIELDS: dict[str, dict] = {
    "grant": {
        "user_id": _f("string", "User ID", required=True, max=64),
        "content_type": _f("enum", "Content", options=list(ACCESS_CONTENT_TYPES), required=True),
        "content_id": _f("string", "Video / package ID", required=True, max=128),
        "duration_hours": _f("int", "Duration (hours, 0 = lifetime)", min=0, max=MAX_DURATION_HOURS, required=True),
    },
    "extend": {
        "hours": _f("int", "Add hours", min=1, max=MAX_DURATION_HOURS),
        "lifetime": _f("bool", "Make lifetime", help="Either hours or lifetime"),
    },
    "revoke": {"reason": _f("string", "Reason", max=300)},
    "ban": {"is_banned": _f("bool", "Banned", required=True), "reason": _f("string", "Reason", max=300)},
}


def extend_expiry(ent: Mapping[str, Any], now: datetime, hours: int | None = None, lifetime: bool = False) -> dict:
    """
    Firestore update for extending ONE entitlement, or raise ValueError(reason).
    Time is added to whichever is later — the current expiry or now — so extending an
    already-expired record gives exactly `hours` from now, never a still-expired date.
    """
    if ent.get("status", ACTIVE) != ACTIVE:
        raise ValueError("entitlement is revoked; grant new access instead")
    if ent.get("is_lifetime") is True:
        raise ValueError("entitlement is already lifetime")
    if lifetime == (hours is not None):
        raise ValueError("send either hours or lifetime=true")
    if lifetime:
        return {"is_lifetime": True, "expires_at": None}
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= MAX_DURATION_HOURS:
        raise ValueError(f"hours must be 1–{MAX_DURATION_HOURS}")
    exp = _aware(ent.get("expires_at"))
    base = max(exp, now) if exp else now
    return {"expires_at": base + timedelta(hours=hours)}


def entitlement_admin_view(ent_id: str, e: Mapping[str, Any], now: datetime) -> dict:
    keys = ("user_id", "content_type", "content_id", "access_source", "order_id", "start_at", "expires_at",
            "is_lifetime", "status", "revoked_reason", "revoked_at", "revoked_by")
    return {"id": ent_id, **{k: e.get(k) for k in keys}, "state": entitlement_state(e, now)}


# ═══ Module registry (merged into admin_config.MODULES) ═══════════════════════
MODULES_1C: dict[str, dict] = {
    "coupons": {
        "label": "Coupons", "view": Perm.COUPONS_MANAGE, "manage": Perm.COUPONS_MANAGE,
        "store": "coupons", "fields": COUPON_FIELDS, "base_path": "/admin/coupons",
        "extra_paths": {"usage": "/admin/coupons/{id}/usage", "active": "/admin/coupons/{id}/active"},
        "read_only": COUPON_READ_ONLY,
    },
    "referral": {
        "label": "Referral", "view": Perm.SETTINGS_MANAGE, "manage": Perm.SETTINGS_MANAGE,
        "store": "app_settings/config", "fields": REFERRAL_FIELDS, "base_path": "/admin/referral-settings",
        "extra_paths": {"referrals": "/admin/referrals"}, "choices": {"statuses": list(REFERRAL_STATUSES)},
        "review_permission": Perm.USERS_VIEW,
    },
    "homepage": {
        "label": "Homepage", "view": Perm.SETTINGS_MANAGE, "manage": Perm.SETTINGS_MANAGE,
        "store": "app_settings/config", "fields": HOMEPAGE_FIELDS, "base_path": "/admin/homepage",
        "choices": {"section_ids": list(HOMEPAGE_SECTION_IDS), "banner_link_types": list(BANNER_LINK_TYPES)},
    },
    "settings": {
        "label": "App settings", "view": Perm.SETTINGS_MANAGE, "manage": Perm.SETTINGS_MANAGE,
        "store": "app_settings/config", "fields": APP_SETTING_FIELDS, "base_path": "/admin/app-settings",
    },
    "notifications": {
        "label": "Notifications", "view": Perm.NOTIFICATIONS_SEND, "manage": Perm.NOTIFICATIONS_SEND,
        "store": "notifications", "fields": NOTIFICATION_FIELDS, "base_path": "/admin/notifications",
        "extra_paths": {"send": "/admin/notifications/send"},
        "choices": {"max_broadcast_users": [MAX_BROADCAST_USERS]},
    },
    "access": {
        "label": "User access", "view": Perm.USERS_VIEW, "manage": Perm.USERS_MANAGE,
        "store": "entitlements", "fields": ACCESS_FIELDS, "base_path": "/admin/users",
        "extra_paths": {"grant": "/admin/entitlements/grant", "revoke": "/admin/entitlements/{id}/revoke",
                        "extend": "/admin/entitlements/{id}/extend", "ban": "/admin/users/{id}/banned"},
    },
}
