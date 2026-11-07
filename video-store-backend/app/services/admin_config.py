"""
Admin configuration structure (Phase 12 / Part 1B) — pure Python, stdlib only.

ONE place that says which fields the admin panel may edit, their limits, and the
allowed choices. The admin API validates with it AND publishes it as
`GET /admin/config/schema`, so the future Admin Panel renders its forms from the
backend and hardcodes no business value (limits, defaults, enums, permissions).

Every value below is derived from the modules that already own it
(source_types, payment_methods, ad_config, ad_providers, payment_verification)
— nothing is duplicated, so the schema cannot drift from the real rules.
No Firestore / network here → unit-testable offline.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from app.core.admin_roles import Perm
from app.services import ad_config as ads
from app.services import payment_methods as pm
from app.services.ad_providers.registry import get_provider, provider_types
from app.services.payment_verification import DEFAULT_RETRY_LIMIT_24H, DEFAULT_VERIFY_MIN_INTERVAL_S
from app.services.source_types import SUPPORTED_SOURCE_TYPES

# ─── Enums / limits (admin choices) ───────────────────────────────────────────
VIDEO_QUALITIES: tuple[str, ...] = ("SD", "HD", "FHD", "4K")      # == schemas.VideoQuality
DURATION_TYPES: tuple[str, ...] = ("lifetime", "custom")           # == schemas.Package.duration_type
MAX_PACKAGE_VIDEOS = 20            # the package detail screen shows at most this many (packages.py)
MAX_DURATION_HOURS = 24 * 365 * 10  # same ceiling ad_config uses; 0 = lifetime
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Payment verification settings live in app_settings/config (read by
# payment_verification.payment_settings). Bounds are enforced here.
PAYMENT_SETTING_BOUNDS: dict[str, tuple[int, int, int]] = {
    # key: (default, min, max)
    "payment_verify_min_interval_seconds": (DEFAULT_VERIFY_MIN_INTERVAL_S, 0, 3600),
    "payment_retry_limit_24h": (DEFAULT_RETRY_LIMIT_24H, 0, 100),
}


# ─── Field specs ──────────────────────────────────────────────────────────────
def _f(type_: str, label: str, **kw: Any) -> dict:
    return {"type": type_, "label": label, **kw}


VIDEO_FIELDS: dict[str, dict] = {
    "title": _f("string", "Title", required=True, max=200),
    "slug": _f("string", "Slug", max=120, pattern=SLUG_RE.pattern, help="Auto-generated from the ID when empty"),
    "description": _f("text", "Description", max=5000),
    "thumbnail_url": _f("url", "Thumbnail URL", https_only=True, max=1000),
    "category_ids": _f("ref_list", "Categories", ref="categories", max=20),
    "primary_category_id": _f("ref", "Primary category", ref="categories", help="Must be one of the selected categories"),
    "quality": _f("enum", "Quality", options=list(VIDEO_QUALITIES)),
    "duration_seconds": _f("int", "Duration (seconds)", min=0, max=86_400),
    "file_size_mb": _f("number", "File size (MB)", min=0, max=1_000_000),
    "price_bdt": _f("number", "Price (BDT)", min=0, max=10_000_000),
    "is_free": _f("bool", "Free"),
    "is_featured": _f("bool", "Featured"),
    "is_trending": _f("bool", "Trending"),
    "is_latest": _f("bool", "Latest"),
    "ads_unlock_enabled": _f("bool", "Unlock by ads"),
    "purchase_enabled": _f("bool", "Purchasable"),
    "ads_required": _f("int", "Ads required", min=1, max=50, default=ads.DEFAULT_ADS_REQUIRED),
    "ads_unlock_duration_hours": _f("int", "Ads unlock duration (hours, 0 = lifetime)",
                                    min=0, max=MAX_DURATION_HOURS, default=ads.DEFAULT_UNLOCK_HOURS),
    "purchase_duration_hours": _f("int", "Purchase duration (hours, 0 = lifetime)", min=0, max=MAX_DURATION_HOURS, default=0),
    "is_published": _f("bool", "Published", default=False, help="New videos start unpublished"),
    "source_type": _f("enum", "Source type", options=list(SUPPORTED_SOURCE_TYPES)),
    "source_url": _f("url", "Source URL", write_only=True, https_only=True, max=2000,
                     help="Stored encrypted; never returned by any API"),
    "backup_source_type": _f("enum", "Backup source type", options=list(SUPPORTED_SOURCE_TYPES)),
    "backup_source_url": _f("url", "Backup source URL", write_only=True, https_only=True, max=2000,
                            help="Optional. Stored encrypted; never returned by any API. Send an empty string to remove it"),
}

PACKAGE_FIELDS: dict[str, dict] = {
    "name": _f("string", "Name", required=True, max=120),
    "description": _f("text", "Description", max=5000),
    "thumbnail_url": _f("url", "Thumbnail URL", https_only=True, max=1000),
    "video_ids": _f("ref_list", "Videos", ref="videos", max=MAX_PACKAGE_VIDEOS,
                    help="`video_count` is derived from this list"),
    "price_bdt": _f("number", "Price (BDT)", min=0, max=10_000_000),
    "original_price_bdt": _f("number", "Original price (BDT)", min=0, max=10_000_000,
                            help="`discount_percentage` is derived from original vs price"),
    "ads_unlock_enabled": _f("bool", "Unlock by ads"),
    "purchase_enabled": _f("bool", "Purchasable"),
    "duration_type": _f("enum", "Duration type", options=list(DURATION_TYPES)),
    "duration_hours": _f("int", "Duration (hours)", min=0, max=MAX_DURATION_HOURS,
                         help="Required (> 0) when duration_type is custom; stored as 0 for lifetime"),
    "ads_required": _f("int", "Ads required", min=1, max=50, default=ads.DEFAULT_ADS_REQUIRED),
    "is_featured": _f("bool", "Featured"),
    "is_published": _f("bool", "Published", default=False),
    "display_order": _f("int", "Display order", min=0, max=10_000, default=100),
}

AD_NETWORK_FIELDS: dict[str, dict] = {
    "name": _f("string", "Name", required=True, max=64),
    "type": _f("enum", "Provider", options=provider_types(), required=True),
    "is_enabled": _f("bool", "Enabled", default=False),
    "priority": _f("int", "Priority (lower = first)", min=0, max=1000),
    "zone_id": _f("string", "Zone ID", max=64, pattern=r"^[A-Za-z0-9_-]*$"),
    "sdk_url": _f("url", "SDK URL", https_only=True, max=300),
    "placements": _f("flags", "Placements", keys=list(ads.PLACEMENTS)),
    "default_ads_required": _f("int", "Default ads required", min=1, max=50, default=ads.DEFAULT_ADS_REQUIRED),
    "unlock_duration_hours": _f("int", "Unlock duration (hours, 0 = lifetime)", min=0, max=MAX_DURATION_HOURS,
                                default=ads.DEFAULT_UNLOCK_HOURS),
    "session_timeout_minutes": _f("int", "Session timeout (minutes)", min=1, max=240,
                                  default=ads.DEFAULT_SESSION_TIMEOUT_MINUTES),
}

PAYMENT_METHOD_FIELDS: dict[str, dict] = {
    "name": _f("string", "Name", required=True, max=80),
    "type": _f("enum_or_slug", "Type", options=sorted(pm.METHOD_TYPES), slug_pattern=pm.TYPE_SLUG_RE.pattern, required=True),
    "is_enabled": _f("bool", "Enabled", default=False),
    "display_order": _f("int", "Display order", min=0, max=10_000, default=100),
    "network_name": _f("string", "Network", max=60),
    "wallet_address": _f("string", "Wallet address", max=200),
    "pay_id": _f("string", "Pay ID", max=40),
    "merchant_name": _f("string", "Merchant name", max=80),
    "qr_code_url": _f("url", "QR code URL", https_only=True, max=1000),
    "currency": _f("string", "Currency", min_len=2, max=10, default="USDT"),
    "min_amount_usdt": _f("number", "Minimum (USDT)", min=0, default=pm.DEFAULT_MIN_USDT),
    "max_amount_usdt": _f("number", "Maximum (USDT)", min_exclusive=0),
    "payment_timeout_minutes": _f("int", "Payment window (minutes)", min=pm.MIN_TIMEOUT_MIN, max=pm.MAX_TIMEOUT_MIN,
                                  default=pm.DEFAULT_TIMEOUT_MIN),
    "instructions_text": _f("text", "Instructions", max=2000),
    "auto_verification_supported": _f("bool", "Automatic verification",
                                      help="Only Binance Pay has an API verifier; other methods are always manual"),
    "manual_review_supported": _f("bool", "Manual review", default=True),
}

PAYMENT_SETTING_FIELDS: dict[str, dict] = {
    "payment_verify_min_interval_seconds": _f(
        "int", "Minimum seconds between Binance status checks per payment",
        default=PAYMENT_SETTING_BOUNDS["payment_verify_min_interval_seconds"][0],
        min=PAYMENT_SETTING_BOUNDS["payment_verify_min_interval_seconds"][1],
        max=PAYMENT_SETTING_BOUNDS["payment_verify_min_interval_seconds"][2]),
    "payment_retry_limit_24h": _f(
        "int", "Failed/expired orders per item per 24h before retry is blocked (0 = no retry)",
        default=PAYMENT_SETTING_BOUNDS["payment_retry_limit_24h"][0],
        min=PAYMENT_SETTING_BOUNDS["payment_retry_limit_24h"][1],
        max=PAYMENT_SETTING_BOUNDS["payment_retry_limit_24h"][2]),
}

# module → (view permission, manage permission, collection/doc, fields, API)
MODULES: dict[str, dict] = {
    "videos": {
        "label": "Videos", "view": Perm.VIDEOS_VIEW, "manage": Perm.VIDEOS_MANAGE,
        "store": "videos", "fields": VIDEO_FIELDS, "base_path": "/admin/videos",
        "relations": [{"field": "category_ids", "to": "categories", "kind": "many"},
                      {"field": "primary_category_id", "to": "categories", "kind": "one"},
                      {"used_by": "packages.video_ids", "kind": "reverse"}],
        "read_only": ["view_count", "purchase_count", "created_at", "updated_at"],
    },
    "packages": {
        "label": "Packages", "view": Perm.VIDEOS_VIEW, "manage": Perm.VIDEOS_MANAGE,
        "store": "packages", "fields": PACKAGE_FIELDS, "base_path": "/admin/packages",
        "relations": [{"field": "video_ids", "to": "videos", "kind": "many"}],
        "derived": ["video_count", "discount_percentage"],
        "read_only": ["purchase_count", "created_at", "updated_at"],
    },
    "ads": {
        "label": "Ads", "view": Perm.ADS_MANAGE, "manage": Perm.ADS_MANAGE,
        "store": "ad_networks", "fields": AD_NETWORK_FIELDS, "base_path": "/admin/ad-networks",
        "extra_paths": {"overview": "/admin/ads-config", "verification": "/admin/ad-networks/{id}/verification"},
        "choices": {"placements": list(ads.PLACEMENTS)},
        "read_only": ["s2s_callback_supported", "s2s_callback_secret_ref"],   # owned by the provider module
    },
    "payments": {
        "label": "Payments", "view": Perm.PAYMENT_METHODS_MANAGE, "manage": Perm.PAYMENT_METHODS_MANAGE,
        "store": "payment_methods", "fields": PAYMENT_METHOD_FIELDS, "base_path": "/admin/payment-methods",
        "extra_paths": {"overview": "/admin/payment-config", "settings": "/admin/payment-settings"},
        "settings_fields": PAYMENT_SETTING_FIELDS,
        "choices": {"builtin_types": sorted(pm.METHOD_TYPES)},
        "review_permission": Perm.PAYMENTS_REVIEW,
    },
}


from app.services.admin_settings import MODULES_1C  # noqa: E402  (Part 1C modules share the same manifest)
from app.services.admin_ops import MODULES_1D  # noqa: E402  (Part 1D modules share the same manifest)

MODULES.update(MODULES_1C)
MODULES.update(MODULES_1D)


def schema_for(permissions: frozenset[str]) -> dict:
    """The manifest the admin UI renders from; `allowed` says whether this admin may use a module."""
    modules = {}
    for key, m in MODULES.items():
        out = {k: v for k, v in m.items() if k not in ("view", "manage")}
        out["permission"] = m["manage"]
        out["can_view"] = m["view"] in permissions or m["manage"] in permissions
        out["can_manage"] = m["manage"] in permissions
        modules[key] = out
    return {"version": "12.1d", "modules": modules}


# ─── Normalisation / validation ───────────────────────────────────────────────
def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s


def _https(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("https://")


def video_problems(data: Mapping[str, Any], *, creating: bool = False) -> list[str]:
    """Problems with a MERGED video document (+ optional `source_url`)."""
    p: list[str] = []
    if not str(data.get("title") or "").strip():
        p.append("title is required")
    slug = data.get("slug")
    if slug and not SLUG_RE.match(str(slug)):
        p.append("slug must be lowercase letters, digits and single hyphens")
    if data.get("quality") is not None and data["quality"] not in VIDEO_QUALITIES:
        p.append(f"quality must be one of {list(VIDEO_QUALITIES)}")
    if data.get("source_type") is not None and data["source_type"] not in SUPPORTED_SOURCE_TYPES:
        p.append(f"source_type must be one of {list(SUPPORTED_SOURCE_TYPES)}")
    if data.get("backup_source_type") is not None and data["backup_source_type"] not in SUPPORTED_SOURCE_TYPES:
        p.append(f"backup_source_type must be one of {list(SUPPORTED_SOURCE_TYPES)}")
    for k in ("thumbnail_url", "source_url", "backup_source_url"):
        if data.get(k) and not _https(data[k]):
            p.append(f"{k} must start with https://")
    if data.get("backup_source_url") and not (data.get("backup_source_type") or data.get("source_type")):
        p.append("backup_source_type is required when a backup source URL is given")
    cats, primary = data.get("category_ids") or [], data.get("primary_category_id")
    if primary and primary not in cats:
        p.append("primary_category_id must be one of category_ids")
    if len(cats) != len(set(cats)):
        p.append("category_ids contains duplicates")
    price, free = data.get("price_bdt"), data.get("is_free")
    if free is not True and data.get("purchase_enabled", True) and price is not None and price <= 0:
        p.append("a purchasable, non-free video needs price_bdt > 0")
    if data.get("is_published") is True and not data.get("has_source", True):
        p.append("cannot publish a video without a source_url")
    return p


def package_problems(data: Mapping[str, Any]) -> list[str]:
    p: list[str] = []
    if not str(data.get("name") or "").strip():
        p.append("name is required")
    ids = data.get("video_ids") or []
    if len(ids) != len(set(ids)):
        p.append("video_ids contains duplicates")
    if len(ids) > MAX_PACKAGE_VIDEOS:
        p.append(f"a package can hold at most {MAX_PACKAGE_VIDEOS} videos")
    if data.get("is_published") is True and not ids:
        p.append("cannot publish an empty package")
    if data.get("thumbnail_url") and not _https(data["thumbnail_url"]):
        p.append("thumbnail_url must start with https://")
    dt = data.get("duration_type")
    if dt is not None and dt not in DURATION_TYPES:
        p.append(f"duration_type must be one of {list(DURATION_TYPES)}")
    if dt == "custom" and not (data.get("duration_hours") or 0) > 0:
        p.append("duration_hours must be > 0 for a custom duration")
    price, orig = data.get("price_bdt"), data.get("original_price_bdt")
    if price is not None and orig is not None and orig < price:
        p.append("original_price_bdt cannot be lower than price_bdt")
    if data.get("purchase_enabled", True) and price is not None and price <= 0:
        p.append("a purchasable package needs price_bdt > 0")
    return p


def package_derived(data: Mapping[str, Any]) -> dict:
    """Fields the server computes (never trusted from the client)."""
    out: dict[str, Any] = {"video_count": len(data.get("video_ids") or [])}
    price, orig = data.get("price_bdt"), data.get("original_price_bdt")
    if price is not None and orig:
        out["discount_percentage"] = round(max(0.0, (orig - price) / orig * 100), 2) if orig > 0 else 0.0
    if data.get("duration_type") == "lifetime":
        out["duration_hours"] = 0
    return out


def payment_setting_problems(changes: Mapping[str, Any]) -> list[str]:
    p: list[str] = []
    for k, v in changes.items():
        if k not in PAYMENT_SETTING_BOUNDS:
            p.append(f"unknown setting {k}")
            continue
        _, lo, hi = PAYMENT_SETTING_BOUNDS[k]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            p.append(f"{k} must be an integer {lo}–{hi}")
    return p


def payment_settings_view(cfg: Mapping[str, Any] | None) -> dict:
    """Effective values (document value, else the backend default) — mirrors payment_settings()."""
    cfg = cfg or {}
    out = {}
    for k, (default, _lo, _hi) in PAYMENT_SETTING_BOUNDS.items():
        try:
            out[k] = max(0, int(cfg.get(k, default)))
        except (TypeError, ValueError):
            out[k] = default
    return out


# ─── Verification readiness (honest: configuration only, never a fake "verified") ─
def ad_network_readiness(network_id: str, network: Mapping[str, Any], secret_present: bool) -> dict:
    """
    Whether an ad network is CONFIGURED to verify ads server-to-server. This does
    not claim any ad was shown or verified — only a real S2S callback (ads.py)
    can unlock content.
    """
    provider = get_provider(network.get("type"))
    if provider is None:
        return {"id": network_id, "ready": False, "provider_known": False,
                "problems": [f"type must be one of {provider_types()}"], "placements": {}}
    problems = list(provider.config_problems(network))
    if not secret_present:
        problems.append(f"backend setting {provider.secret_setting} is not set (callbacks would be rejected)")
    if network.get("s2s_callback_supported") is not True:
        problems.append("s2s_callback_supported is not recorded; save the network once to refresh it")
    placements = {}
    for pl in ads.PLACEMENTS:
        usable_here = bool(ads.rank_networks([(network_id, network)], pl))
        placements[pl] = usable_here
    return {
        "id": network_id, "provider_known": True, "provider": provider.type,
        "supports_s2s": provider.supports_s2s, "secret_setting": provider.secret_setting,
        "secret_configured": secret_present, "enabled": network.get("is_enabled") is True,
        "priority": network.get("priority"), "placements": placements,
        "problems": problems,
        "ready": not problems and network.get("is_enabled") is True,
    }


def binance_readiness(api_key: str, api_secret: str, merchant_id: str) -> dict:
    """Which Binance Pay credentials the backend has (booleans only — never values)."""
    have = {"api_key": bool(api_key), "api_secret": bool(api_secret), "merchant_id": bool(merchant_id)}
    return {"credentials": have, "configured": all(have.values()),
            "missing_settings": [n for n, ok in (("BINANCE_PAY_API_KEY", have["api_key"]),
                                                 ("BINANCE_PAY_API_SECRET", have["api_secret"]),
                                                 ("BINANCE_PAY_MERCHANT_ID", have["merchant_id"])) if not ok]}
