"""
Ad provider contract (stdlib only → unit-testable without FastAPI/Firestore).

A provider is ONE module that knows how to:
  * describe itself (type id, S2S support, which setting holds its secret),
  * validate its own network config (what must be set before it can be enabled),
  * expose only PUBLIC client config (never secrets),
  * verify its server-to-server callback and extract (session_id, ad_id).

Access is never granted from anything the browser reports. The only path to an
entitlement is a callback that `verify_callback` accepted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping


class CallbackRejected(Exception):
    """Callback must not be processed. `status` is the HTTP code to return."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class CallbackEvent:
    session_id: str
    ad_id: str | None  # unique per completed ad; None → cannot be counted
    telegram_id: str | None = None  # user id the NETWORK saw (if it reports one)
    zone_id: str | None = None      # zone the NETWORK says served the ad


class AdProvider(ABC):
    #: stable provider id stored in ad_networks/{id}.type
    type: str = ""
    #: human readable default name
    display_name: str = ""
    #: only providers with real S2S verification may unlock content
    supports_s2s: bool = False
    #: name of the backend setting (env var) holding the callback secret.
    #: Only the NAME lives in Firestore (`s2s_callback_secret_ref`), never the value.
    secret_setting: str = ""
    #: network config fields that must be non-empty before the network is enabled
    required_fields: tuple[str, ...] = ()

    @abstractmethod
    def verify_callback(
        self,
        secret: str,
        headers: Mapping[str, str],
        body: bytes,
        query: Mapping[str, str] | None = None,
    ) -> CallbackEvent:
        """Return the verified event or raise CallbackRejected."""

    def public_config(self, network_id: str, network: Mapping) -> dict:
        """Client-safe subset of the network config. Never include secrets."""
        sdk_url = network.get("sdk_url")
        if not (isinstance(sdk_url, str) and sdk_url.startswith("https://")):
            sdk_url = None
        return {
            "network_id": network_id,
            "provider_id": self.type,
            "zone_id": network.get("zone_id"),
            "type": self.type,
            "sdk_url": sdk_url,
        }

    def config_problems(self, network: Mapping) -> list[str]:
        """Reasons this network cannot be enabled (empty = ok)."""
        problems = [f"{f} is required" for f in self.required_fields if not network.get(f)]
        if not self.supports_s2s:
            problems.append("provider has no S2S verification")
        return problems
