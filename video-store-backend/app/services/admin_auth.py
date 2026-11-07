"""
Admin authentication.

Accounts live in the existing Firestore database, collection `admin_users`
(document id = lower-case username):
    password_hash (bcrypt) · role · is_active · display_name · token_version
    failed_attempts · locked_until · last_login_at · created_at / updated_at

The ADMIN_USERNAME / ADMIN_PASSWORD_HASH environment account keeps working as a
bootstrap SUPER ADMIN (so existing deployments are not locked out). A Firestore
record with the same username takes precedence over it.

Brute force: per-account lockout (5 failures → 15 min) for Firestore accounts,
plus the per-IP limit on POST /admin/login (core.rate_limit) for every account.
"""
from __future__ import annotations

import asyncio
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.admin_roles import ROLES, SUPER_ADMIN, AdminContext
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.firebase import Col, get_db

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")

_dummy_hash: str | None = None


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


async def _verify(plain: str, hashed: str | None) -> bool:
    """bcrypt off the event loop. Always does the work, even with no hash."""
    global _dummy_hash
    if not hashed:
        if _dummy_hash is None:
            _dummy_hash = await asyncio.to_thread(hash_password, "not-a-real-password")
        await asyncio.to_thread(verify_password, plain, _dummy_hash)  # equalise timing
        return False
    try:
        return bool(await asyncio.to_thread(verify_password, plain, hashed))
    except Exception:
        return False


def _env_admin_matches(uname: str) -> bool:
    env_name = normalize_username(settings.ADMIN_USERNAME)
    return bool(env_name) and hmac.compare_digest(uname.encode(), env_name.encode())


def _env_context() -> AdminContext:
    return AdminContext(
        username=normalize_username(settings.ADMIN_USERNAME),
        role=SUPER_ADMIN, display_name="Super Admin", source="env",
    )


async def _load_record(uname: str):
    """(doc_ref, data) for a Firestore admin, or (None, None)."""
    if not USERNAME_RE.fullmatch(uname):
        return None, None
    ref = get_db().collection(Col.ADMIN_USERS).document(uname)
    snap = await ref.get()
    return (ref, snap.to_dict() or {}) if snap.exists else (None, None)


def _context_from_record(uname: str, rec: dict) -> AdminContext | None:
    role = rec.get("role")
    if role not in ROLES:
        return None
    return AdminContext(
        username=uname, role=role,
        display_name=str(rec.get("display_name") or uname), source="firestore",
    )


@dataclass
class AuthResult:
    ctx: AdminContext | None = None
    token_version: int = 0
    status: str = "invalid"      # ok | invalid | locked | disabled
    retry_after: int = 0


async def authenticate_admin(username: str, password: str) -> AuthResult:
    uname = normalize_username(username)
    now = datetime.now(timezone.utc)
    ref, rec = await _load_record(uname)

    if rec is not None:
        locked_until = rec.get("locked_until")
        if locked_until and locked_until > now:
            return AuthResult(status="locked", retry_after=int((locked_until - now).total_seconds()) + 1)
        ok = await _verify(password, rec.get("password_hash"))
        if not ok:
            fails = int(rec.get("failed_attempts") or 0) + 1
            upd: dict = {"failed_attempts": fails, "updated_at": now}
            if fails >= MAX_FAILED_ATTEMPTS:
                upd.update(failed_attempts=0, locked_until=now + timedelta(minutes=LOCK_MINUTES))
            await ref.update(upd)
            return AuthResult(status="invalid")
        ctx = _context_from_record(uname, rec)
        if rec.get("is_active") is not True or ctx is None:
            return AuthResult(status="disabled")   # only revealed after a correct password
        await ref.update({"failed_attempts": 0, "locked_until": None, "last_login_at": now})
        return AuthResult(ctx=ctx, token_version=int(rec.get("token_version") or 0), status="ok")

    if _env_admin_matches(uname):
        ok = await _verify(password, settings.ADMIN_PASSWORD_HASH)
        return AuthResult(ctx=_env_context(), status="ok") if ok else AuthResult(status="invalid")

    await _verify(password, None)
    return AuthResult(status="invalid")


async def resolve_admin_session(claims: dict) -> AdminContext | None:
    """
    Re-check a verified token against the database on every request:
    account still exists, is active, role still valid, tokens not revoked.
    The role is taken from the database — never from the token.
    """
    uname = normalize_username(claims.get("sub", ""))
    try:
        tv = int(claims.get("tv") or 0)
    except (TypeError, ValueError):
        return None
    _, rec = await _load_record(uname)
    if rec is not None:
        if rec.get("is_active") is not True or int(rec.get("token_version") or 0) != tv:
            return None
        return _context_from_record(uname, rec)
    if _env_admin_matches(uname) and tv == 0:
        return _env_context()
    return None
