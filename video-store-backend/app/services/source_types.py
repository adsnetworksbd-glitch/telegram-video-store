"""
Video source-type normalisation (pure Python — no FastAPI / Firebase / pydantic).

The `source_type` of a video is admin-entered data in Firestore. The response
schemas only accept the types the frontend has handlers for, so an unexpected
value (typo, a type added by hand, e.g. "youtube") used to turn the video
detail / source endpoints into a 500. Unknown values now degrade to
"custom_url", which the frontend already shows with an explicit "link may not
open / may not be downloadable" note. The stored document is never modified.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_SOURCE_TYPES: tuple[str, ...] = (
    "telegram_bot", "telegram_channel",
    "google_drive", "dropbox",
    "direct_mp4", "custom_url",
)

FALLBACK_SOURCE_TYPE = "custom_url"


def normalize_source_type(value: Any) -> str:
    """Return `value` when it is a supported source type, else the fallback."""
    if isinstance(value, str) and value in SUPPORTED_SOURCE_TYPES:
        return value
    return FALLBACK_SOURCE_TYPE
