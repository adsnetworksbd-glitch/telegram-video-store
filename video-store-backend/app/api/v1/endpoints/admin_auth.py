"""
Admin authentication endpoints: login + current admin.
Role/permission checks for the other admin routes live in app.core.deps.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.admin_roles import AdminContext
from app.core.deps import get_admin_context
from app.core.rate_limit import client_ip
from app.core.security import ADMIN_TOKEN_EXPIRE_MINUTES, create_admin_token
from app.services.admin_auth import authenticate_admin
from app.utils.audit import audit_log

router = APIRouter(prefix="/admin", tags=["admin-auth"])


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
async def admin_login(body: AdminLoginRequest, request: Request):
    res = await authenticate_admin(body.username, body.password)
    ip = client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:200]
    who = body.username.strip()[:64]

    if res.status != "ok" or res.ctx is None:
        await audit_log(
            action="admin_login_failed", performed_by=who, target_type="admin",
            target_id="login", after={"reason": res.status}, ip=ip, user_agent=ua,
        )
        if res.status == "locked":
            raise HTTPException(
                status_code=429, detail="Too many failed attempts. Try again later.",
                headers={"Retry-After": str(res.retry_after)},
            )
        if res.status == "disabled":
            raise HTTPException(status_code=403, detail="This admin account is disabled")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await audit_log(
        action="admin_login", performed_by=res.ctx.username, target_type="admin",
        target_id="login", after={"role": res.ctx.role, "source": res.ctx.source},
        ip=ip, user_agent=ua,
    )
    return {
        "access_token": create_admin_token(res.ctx.username, res.token_version),
        "token_type": "bearer",
        "expires_in": ADMIN_TOKEN_EXPIRE_MINUTES * 60,
        "admin": res.ctx.public(),
    }


@router.get("/me")
async def admin_me(ctx: AdminContext = Depends(get_admin_context)):
    """Who am I + what may I do (re-validated against the database)."""
    return {"admin": ctx.public()}
