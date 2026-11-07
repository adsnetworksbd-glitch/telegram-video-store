"""
Admin operations rules (Phase 12 / Part 1D) — pure Python, stdlib only.

Dashboard, orders & transactions, users, support, audit log, categories and admin
accounts. Same idea as admin_config.py / admin_settings.py: ONE place holds field
specs, limits and validation; the admin API validates with it and the schema
endpoint publishes it, so the Admin Panel hardcodes nothing.

Read views are WHITELISTS (a new Firestore field is never leaked by accident) and
audit snapshots are redacted. No Firestore / network here → unit-testable offline.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from app.core.admin_roles import ROLES, SUPER_ADMIN, Perm


def _f(type_: str, label: str, **kw: Any) -> dict:
    return {"type": type_, "label": label, **kw}


def _aware(dt: Any) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ═══ Orders / transactions ════════════════════════════════════════════════════
# Statuses the order flow really writes (orders.py / fulfillment.py).
ORDER_STATUSES: tuple[str, ...] = (
    "awaiting_payment", "payment_submitted", "under_review", "completed", "failed", "expired", "refunded",
)
REVIEW_STATUSES: tuple[str, ...] = ("payment_submitted", "under_review")   # waiting for an admin
ORDER_CONTENT_TYPES: tuple[str, ...] = ("video", "package")
TRANSACTION_DIRECTIONS: tuple[str, ...] = ("credit", "debit")

_ORDER_KEYS = ("user_id", "content_type", "content_id", "amount_bdt", "coupon_code", "discount_bdt", "final_bdt",
               "final_usdt", "currency", "usdt_rate_at_creation", "payment_method_id", "payment_method_type",
               "status", "created_at", "expires_at", "submitted_at", "completed_at", "entitlement_id")
_TX_KEYS = ("user_id", "type", "amount_bdt", "direction", "reference_type", "reference_id", "description", "created_at")
_USER_KEYS = ("username", "first_name", "last_name", "language_code", "is_banned", "account_status", "ban_reason",
              "banned_at", "banned_by", "total_spent_bdt", "referral_code", "referred_by", "created_at", "last_login_at")


def order_admin_view(order_id: str, od: Mapping[str, Any]) -> dict:
    return {"id": order_id, **{k: od.get(k) for k in _ORDER_KEYS}}


def transaction_admin_view(tx_id: str, tx: Mapping[str, Any]) -> dict:
    return {"id": tx_id, **{k: tx.get(k) for k in _TX_KEYS}}


def user_admin_view(uid: str, u: Mapping[str, Any]) -> dict:
    out = {"id": uid, **{k: u.get(k) for k in _USER_KEYS}}
    out["is_banned"] = bool(u.get("is_banned")) or u.get("account_status") == "banned"
    return out


def matches_user_query(uid: str, u: Mapping[str, Any], q: str) -> bool:
    """Case-insensitive match on id, @username and name (Firestore has no full-text search)."""
    needle = (q or "").strip().lstrip("@").lower()
    if not needle:
        return True
    hay = (uid, u.get("username"), u.get("first_name"), u.get("last_name"), u.get("referral_code"))
    return any(needle in str(h).lower() for h in hay if h)


# ═══ Dashboard ════════════════════════════════════════════════════════════════
DASHBOARD_WINDOW_DAYS = 30
DASHBOARD_ORDER_CAP = 5000          # orders read per dashboard call (bounded cost)
DASHBOARD_RECENT_ORDERS = 8         # "recent purchases" list
DASHBOARD_RECENT_ACTIVITY = 10      # "recent activities" list (audit log, newest first)
_VIDEO_STAT_KEYS = ("title", "thumbnail_url", "is_published", "price_bdt", "is_free", "view_count", "purchase_count")


def video_stat_view(v: Mapping[str, Any]) -> dict:
    """Whitelisted per-video numbers for the dashboard (never the source link)."""
    out = {k: v.get(k) for k in _VIDEO_STAT_KEYS}
    out["view_count"] = out["view_count"] if isinstance(out["view_count"], int) else 0
    out["purchase_count"] = out["purchase_count"] if isinstance(out["purchase_count"], int) else 0
    return out


def summarize_orders(orders: Iterable[Mapping[str, Any]], now: datetime) -> dict:
    """Counts and revenue from orders already limited to the dashboard window."""
    now = _aware(now) or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    by_status = {s: 0 for s in ORDER_STATUSES}
    rev = {"today": 0.0, "last_7_days": 0.0, "last_30_days": 0.0}
    orders_today = 0
    total = 0
    for od in orders:
        total += 1
        st = od.get("status")
        if st in by_status:
            by_status[st] += 1
        created = _aware(od.get("created_at"))
        if created and created >= day_start:
            orders_today += 1
        if st == "completed":        # money counts only when fulfilment finished
            amt = od.get("final_bdt")
            amt = float(amt) if isinstance(amt, (int, float)) and not isinstance(amt, bool) else 0.0
            done = _aware(od.get("completed_at")) or created
            rev["last_30_days"] += amt
            if done and done >= week_start:
                rev["last_7_days"] += amt
            if done and done >= day_start:
                rev["today"] += amt
    return {"window_days": DASHBOARD_WINDOW_DAYS, "orders_in_window": total, "orders_today": orders_today,
            "by_status": by_status, "awaiting_review": sum(by_status[s] for s in REVIEW_STATUSES),
            "revenue_bdt": {k: round(v, 2) for k, v in rev.items()}}


# ═══ Support ══════════════════════════════════════════════════════════════════
TICKET_STATUSES: tuple[str, ...] = ("open", "in_progress", "resolved", "closed")
TICKET_REPLY_MAX = 2000
FAQ_FIELDS: dict[str, dict] = {
    "question": _f("string", "Question", required=True, max=300),
    "answer": _f("text", "Answer", required=True, max=3000),
    "display_order": _f("int", "Display order", min=0, max=10_000, default=100),
    "is_visible": _f("bool", "Visible", default=True),
}
TICKET_FIELDS: dict[str, dict] = {
    "status": _f("enum", "Status", options=list(TICKET_STATUSES), required=True),
    "reply": _f("text", "Reply to user", max=TICKET_REPLY_MAX, help="Saved on the ticket and sent to the user as a notification"),
}
_TICKET_KEYS = ("user_id", "subject", "message", "category", "status", "created_at", "resolved_at",
                "admin_reply", "replied_by", "replied_at", "updated_at")


def ticket_admin_view(ticket_id: str, t: Mapping[str, Any]) -> dict:
    return {"id": ticket_id, **{k: t.get(k) for k in _TICKET_KEYS}}


def ticket_status_changes(new_status: str, now: datetime, admin: str) -> dict:
    """resolved/closed stamp `resolved_at`; re-opening clears it."""
    if new_status not in TICKET_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(TICKET_STATUSES)}")
    done = new_status in ("resolved", "closed")
    return {"status": new_status, "resolved_at": now if done else None, "updated_at": now, "updated_by": admin}


def faq_problems(faq: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for key, lo_hi in (("question", (1, 300)), ("answer", (1, 3000))):
        v = faq.get(key)
        if not isinstance(v, str) or not lo_hi[0] <= len(v.strip()) <= lo_hi[1]:
            out.append(f"{key} must be {lo_hi[0]}–{lo_hi[1]} characters")
    order = faq.get("display_order", 100)
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10_000:
        out.append("display_order must be an integer 0–10000")
    if not isinstance(faq.get("is_visible", True), bool):
        out.append("is_visible must be true or false")
    return out


# ═══ Audit log ════════════════════════════════════════════════════════════════
AUDIT_SCAN_CAP = 2000               # newest entries scanned per request
_SECRET_RE = re.compile(r"(password|passwd|secret|token|hash|api_?key|source_url|encrypted|credential|authorization)", re.I)
_AUDIT_KEYS = ("action", "performed_by", "target_type", "target_id", "snapshot_before", "snapshot_after",
               "ip_address", "created_at")


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively blank secret-looking keys. Depth-limited so a hostile snapshot cannot blow the stack."""
    if _depth > 6:
        return "[truncated]"
    if isinstance(value, Mapping):
        return {k: ("[redacted]" if _SECRET_RE.search(str(k)) else redact(v, _depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in list(value)[:100]]
    return value


def audit_admin_view(log_id: str, a: Mapping[str, Any]) -> dict:
    out = {"id": log_id, **{k: a.get(k) for k in _AUDIT_KEYS}}
    out["snapshot_before"] = redact(out["snapshot_before"])
    out["snapshot_after"] = redact(out["snapshot_after"])
    return out


def audit_matches(a: Mapping[str, Any], *, action: str | None = None, performed_by: str | None = None,
                  target_type: str | None = None, target_id: str | None = None,
                  since: datetime | None = None, until: datetime | None = None) -> bool:
    if action and a.get("action") != action:
        return False
    if performed_by and a.get("performed_by") != performed_by:
        return False
    if target_type and a.get("target_type") != target_type:
        return False
    if target_id and a.get("target_id") != target_id:
        return False
    created = _aware(a.get("created_at"))
    if since and (created is None or created < _aware(since)):
        return False
    if until and (created is None or created > _aware(until)):
        return False
    return True


# ═══ Categories ═══════════════════════════════════════════════════════════════
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY_FIELDS: dict[str, dict] = {
    "name": _f("string", "Name", required=True, max=80),
    "slug": _f("string", "Slug", max=80, pattern=SLUG_RE.pattern, help="Auto-generated from the ID when empty"),
    "description": _f("text", "Description", max=500),
    "thumbnail_url": _f("url", "Thumbnail URL", https_only=True, max=1000),
    "display_order": _f("int", "Display order", min=0, max=10_000, default=100),
    "is_visible": _f("bool", "Visible in the app", default=False, help="New categories start hidden"),
}
CATEGORY_READ_ONLY = ["video_count", "created_at", "updated_at"]


def category_problems(cat: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    name = cat.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        out.append("name must be 1–80 characters")
    slug = cat.get("slug")
    if slug is not None and (not isinstance(slug, str) or len(slug) > 80 or not SLUG_RE.match(slug)):
        out.append("slug must be lower-case letters, digits and single hyphens")
    desc = cat.get("description")
    if desc is not None and (not isinstance(desc, str) or len(desc) > 500):
        out.append("description must be at most 500 characters")
    thumb = cat.get("thumbnail_url")
    if thumb not in (None, "") and (not isinstance(thumb, str) or not thumb.startswith("https://") or len(thumb) > 1000):
        out.append("thumbnail_url must be an https:// URL (max 1000 characters)")
    order = cat.get("display_order", 100)
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10_000:
        out.append("display_order must be an integer 0–10000")
    if not isinstance(cat.get("is_visible", False), bool):
        out.append("is_visible must be true or false")
    return out


# ═══ Admin accounts ═══════════════════════════════════════════════════════════
PASSWORD_MIN_BYTES, PASSWORD_MAX_BYTES = 10, 72          # same bounds as scripts/create_admin.py (bcrypt limit)
ADMIN_ACCOUNT_FIELDS: dict[str, dict] = {
    "username": _f("string", "Username", required=True, create_only=True, pattern=r"^[a-z0-9][a-z0-9_.-]{2,31}$",
                   help="3–32 chars: a-z 0-9 . _ -  — cannot be changed"),
    "display_name": _f("string", "Display name", max=60),
    "role": _f("enum", "Role", options=list(ROLES), required=True),
    "is_active": _f("bool", "Active", default=True, help="Disabling signs the account out immediately"),
    "password": _f("string", "Password", write_only=True, min_len=PASSWORD_MIN_BYTES, max=PASSWORD_MAX_BYTES,
                   help="Write-only; stored as a bcrypt hash, never returned"),
}
ADMIN_READ_ONLY = ["source", "last_login_at", "created_at", "updated_at", "created_by"]
_ADMIN_KEYS = ("display_name", "role", "is_active", "last_login_at", "created_at", "updated_at", "created_by")


def password_problem(pw: Any) -> str | None:
    if not isinstance(pw, str) or not PASSWORD_MIN_BYTES <= len(pw.encode()) <= PASSWORD_MAX_BYTES:
        return f"password must be {PASSWORD_MIN_BYTES}–{PASSWORD_MAX_BYTES} bytes long"
    if pw.strip() != pw or len(set(pw)) < 4:
        return "password must not start/end with spaces and must not be trivially repetitive"
    return None


def admin_account_view(username: str, rec: Mapping[str, Any], source: str = "firestore") -> dict:
    """Never includes password_hash, token_version or lockout internals."""
    out = {"username": username, "source": source, **{k: rec.get(k) for k in _ADMIN_KEYS}}
    locked = _aware(rec.get("locked_until"))
    out["is_locked"] = bool(locked and locked > datetime.now(timezone.utc))
    return out


def admin_change_problem(
    *, actor: str, target: str, target_role: str | None, target_active: bool,
    new_role: str | None, new_active: bool | None, other_active_super_admins: int,
) -> str | None:
    """
    Safety rules for editing an admin account (None = allowed).
      · you cannot change your own role or active flag (ask another super admin),
      · the system must always keep at least one active super admin.
    """
    if new_role is not None and new_role not in ROLES:
        return f"role must be one of: {', '.join(ROLES)}"
    role_changes = new_role is not None and new_role != target_role
    active_changes = new_active is not None and new_active != target_active
    if actor == target and (role_changes or active_changes):
        return "You cannot change your own role or active status"
    loses_super = target_role == SUPER_ADMIN and target_active and (
        (role_changes and new_role != SUPER_ADMIN) or (new_active is False)
    )
    if loses_super and other_active_super_admins < 1:
        return "At least one active super admin must remain"
    return None


# ═══ Module registry (merged into admin_config.MODULES) ═══════════════════════
MODULES_1D: dict[str, dict] = {
    "dashboard": {
        "label": "Dashboard", "view": Perm.DASHBOARD_VIEW, "manage": Perm.DASHBOARD_VIEW,
        "store": "orders", "fields": {}, "base_path": "/admin/dashboard",
        "choices": {"window_days": [DASHBOARD_WINDOW_DAYS]},
    },
    "orders": {
        "label": "Orders", "view": Perm.ORDERS_VIEW, "manage": Perm.PAYMENTS_REVIEW,
        "store": "orders", "fields": {}, "base_path": "/admin/orders",
        "extra_paths": {"transactions": "/admin/transactions", "review": "/admin/payments/pending"},
        "choices": {"statuses": list(ORDER_STATUSES), "review_statuses": list(REVIEW_STATUSES),
                    "content_types": list(ORDER_CONTENT_TYPES), "transaction_directions": list(TRANSACTION_DIRECTIONS)},
        "read_only": list(_ORDER_KEYS),
    },
    "users": {
        "label": "Users", "view": Perm.USERS_VIEW, "manage": Perm.USERS_MANAGE,
        "store": "users", "fields": {}, "base_path": "/admin/users",
        "extra_paths": {"access": "/admin/users/{id}/access", "ban": "/admin/users/{id}/banned"},
        "read_only": list(_USER_KEYS),
    },
    "support": {
        "label": "Support", "view": Perm.SUPPORT_MANAGE, "manage": Perm.SUPPORT_MANAGE,
        "store": "support_tickets", "fields": TICKET_FIELDS, "base_path": "/admin/support/tickets",
        "extra_paths": {"reply": "/admin/support/tickets/{id}/reply", "status": "/admin/support/tickets/{id}/status",
                        "faqs": "/admin/faqs"},
        "settings_fields": FAQ_FIELDS,
        "choices": {"statuses": list(TICKET_STATUSES)},
        "read_only": list(_TICKET_KEYS),
    },
    "audit": {
        "label": "Audit log", "view": Perm.AUDIT_VIEW, "manage": Perm.AUDIT_VIEW,
        "store": "audit_logs", "fields": {}, "base_path": "/admin/audit-logs",
        "read_only": list(_AUDIT_KEYS),
    },
    "categories": {
        "label": "Categories", "view": Perm.VIDEOS_VIEW, "manage": Perm.VIDEOS_MANAGE,
        "store": "categories", "fields": CATEGORY_FIELDS, "base_path": "/admin/categories",
        "read_only": CATEGORY_READ_ONLY,
    },
    "admins": {
        "label": "Admin accounts", "view": Perm.ADMINS_MANAGE, "manage": Perm.ADMINS_MANAGE,
        "store": "admin_users", "fields": ADMIN_ACCOUNT_FIELDS, "base_path": "/admin/admins",
        "extra_paths": {"password": "/admin/admins/{username}/password"},
        "choices": {"roles": list(ROLES)},
        "read_only": ADMIN_READ_ONLY,
    },
}
