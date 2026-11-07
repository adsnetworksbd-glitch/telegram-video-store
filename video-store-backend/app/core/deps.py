"""
FastAPI dependency injection.
All protected endpoints use Depends(get_current_user).
Admin endpoints use Depends(get_current_admin) + dependencies=[Depends(require_permission(Perm.X))].
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.admin_roles import AdminContext
from app.core.security import decode_access_token
from app.db.firebase import get_db, Col
from app.services.user_auth import is_blocked

# auto_error=False: with FastAPI 0.111 a MISSING Authorization header would
# otherwise produce 403, but the frontend's refresh-and-retry logic only reacts
# to 401. We raise 401 ourselves so "no/expired token" is always 401.
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Extract and verify JWT.
    Returns telegram_user_id (str).
    Raises 401 on missing/invalid/expired token.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user exists and is not banned
    db = get_db()
    doc = await db.collection(Col.USERS).document(user_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    data = doc.to_dict() or {}
    if is_blocked(data):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account banned")

    return user_id


# ─── Admin auth (separate token, role=admin) ──────────────────────────────────
# 401 = not logged in / token invalid, expired or revoked / account disabled.
# 403 = logged in but the role lacks the permission.
_admin_bearer = HTTPBearer(auto_error=False)


async def get_admin_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
) -> AdminContext:
    """
    Verified admin identity + role, re-checked against Firestore on each request
    (FastAPI caches it per request, so guards stacked on one route read once).
    """
    from app.core.security import decode_admin_claims
    from app.services.admin_auth import resolve_admin_session

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        claims = decode_admin_claims(credentials.credentials)
    except Exception:
        raise unauthorized
    ctx = await resolve_admin_session(claims)
    if ctx is None:
        raise unauthorized
    return ctx


async def get_current_admin(ctx: AdminContext = Depends(get_admin_context)) -> str:
    """Any active admin (every role). Returns the username."""
    return ctx.username


def require_permission(*permissions: str):
    """
    Route guard: `dependencies=[Depends(require_permission(Perm.X))]`.
    A refused attempt is written to the audit log.
    """
    async def _guard(request: Request, ctx: AdminContext = Depends(get_admin_context)) -> AdminContext:
        missing = [p for p in permissions if not ctx.can(p)]
        if missing:
            from app.core.rate_limit import client_ip
            from app.utils.audit import audit_log
            await audit_log(
                action="admin_permission_denied", performed_by=ctx.username,
                target_type="admin_route", target_id=f"{request.method} {request.url.path}"[:200],
                after={"role": ctx.role, "required": missing}, ip=client_ip(request),
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return ctx
    return _guard
