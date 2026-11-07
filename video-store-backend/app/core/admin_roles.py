"""
Admin roles & permissions (pure Python, no I/O — unit-testable on its own).

Three roles. Every protected admin route names ONE permission; a role is allowed
exactly when the permission is in its set. Later admin modules only need to pick
an existing permission (or add one here) — no per-route role checks.
"""
from __future__ import annotations

from dataclasses import dataclass

SUPER_ADMIN = "super_admin"
ADMIN = "admin"
MODERATOR = "moderator"
ROLES: tuple[str, ...] = (SUPER_ADMIN, ADMIN, MODERATOR)


class Perm:
    DASHBOARD_VIEW = "dashboard.view"
    VIDEOS_VIEW = "videos.view"
    VIDEOS_MANAGE = "videos.manage"        # videos, categories, packages, homepage
    ORDERS_VIEW = "orders.view"
    PAYMENTS_REVIEW = "payments.review"    # approve / reject / re-verify
    USERS_VIEW = "users.view"
    USERS_MANAGE = "users.manage"          # ban / unban, adjustments
    COUPONS_MANAGE = "coupons.manage"
    SUPPORT_MANAGE = "support.manage"
    NOTIFICATIONS_SEND = "notifications.send"
    AUDIT_VIEW = "audit.view"
    ADS_MANAGE = "ads.manage"
    PAYMENT_METHODS_MANAGE = "payment_methods.manage"
    SETTINGS_MANAGE = "settings.manage"
    ADMINS_MANAGE = "admins.manage"


ALL_PERMISSIONS: frozenset[str] = frozenset(
    v for k, v in vars(Perm).items() if not k.startswith("_") and isinstance(v, str)
)

_MODERATOR = frozenset({
    Perm.DASHBOARD_VIEW, Perm.VIDEOS_VIEW, Perm.ORDERS_VIEW,
    Perm.USERS_VIEW, Perm.SUPPORT_MANAGE,
})
# Money-routing / system-level settings stay with the super admin.
_SUPER_ONLY = frozenset({
    Perm.ADS_MANAGE, Perm.PAYMENT_METHODS_MANAGE, Perm.SETTINGS_MANAGE, Perm.ADMINS_MANAGE,
})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    SUPER_ADMIN: ALL_PERMISSIONS,
    ADMIN: ALL_PERMISSIONS - _SUPER_ONLY,
    MODERATOR: _MODERATOR,
}


def permissions_for(role: str | None) -> frozenset[str]:
    """Unknown / missing role → no permissions (fail closed)."""
    return ROLE_PERMISSIONS.get(role or "", frozenset())


@dataclass(frozen=True)
class AdminContext:
    username: str
    role: str
    display_name: str
    source: str  # "firestore" | "env"

    @property
    def permissions(self) -> frozenset[str]:
        return permissions_for(self.role)

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def public(self) -> dict:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "permissions": sorted(self.permissions),
        }
