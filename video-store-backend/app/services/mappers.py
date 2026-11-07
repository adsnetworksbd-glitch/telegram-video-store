"""
Pure Firestore-dict → response-schema mappers.

Only depends on pydantic + app.schemas (no FastAPI / Firebase), so they can be
unit-tested offline. They never invent business data: a missing optional
field falls back to the SAME safe default the endpoints already used
(see config.py "safe defaults"), and a malformed value is dropped instead of
turning the whole endpoint (and therefore the whole app) into a 500.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas import AppConfig, Category

# Same values config.py returned when app_settings/config did not exist.
APP_CONFIG_DEFAULTS: dict[str, Any] = {
    "app_name": "Video Store",
    "app_logo_url": None,
    "maintenance_mode": False,
    "maintenance_message": "",
    "currency_display": "BDT",
    "usdt_to_bdt_rate": 115.0,
    "referral_enabled": True,
    "wallet_enabled": False,
    "homepage_announcement": None,
    "homepage_announcement_url": None,
    "terms_url": None,
    "privacy_url": None,
    "support_username": None,
    "support_url": None,
}


def _validated(model, defaults: dict[str, Any], raw: dict[str, Any]):
    """Build `model` from raw∪defaults; drop fields that fail validation."""
    values = {**defaults, **{k: v for k, v in raw.items() if k in defaults and v is not None}}
    for _ in range(len(defaults) + 1):
        try:
            return model(**values)
        except ValidationError as e:
            bad = {err["loc"][0] for err in e.errors() if err.get("loc")}
            if not bad:
                raise
            for k in bad:
                values[k] = defaults.get(k)
    return model(**defaults)


def build_app_config(data: dict[str, Any] | None) -> AppConfig:
    return _validated(AppConfig, APP_CONFIG_DEFAULTS, data or {})


class _CategoryBody(BaseModel):
    """Category minus `id`, so `_validated` can reuse the drop-bad-field logic."""
    name: str
    slug: str
    thumbnail_url: str
    description: str | None
    video_count: int
    display_order: int


def build_category(doc_id: str, data: dict[str, Any] | None) -> Category:
    data = data or {}
    defaults = {
        "name": "",
        "slug": doc_id,
        "thumbnail_url": "",
        "description": None,
        "video_count": 0,
        "display_order": 0,
    }
    cat = _validated(_CategoryBody, defaults, data)
    return Category(id=doc_id, **cat.model_dump())
