"""Provider registry. Adding a network = new module + one line here."""
from __future__ import annotations

from app.services.ad_providers.base import AdProvider
from app.services.ad_providers.monetag import MonetagProvider

_PROVIDERS: dict[str, AdProvider] = {p.type: p for p in (MonetagProvider(),)}


def get_provider(provider_type: str | None) -> AdProvider | None:
    return _PROVIDERS.get(provider_type or "")


def provider_types() -> list[str]:
    return sorted(_PROVIDERS)
