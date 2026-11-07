"""
Security utilities:
- Telegram initData HMAC verification
- JWT RS256 issue / decode
- Source URL AES encryption / decryption
- Password hashing (admin only)
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core import auto_secrets
from app.core.config import settings
from app.core.telegram_auth import (  # noqa: F401  (re-exported for callers)
    TelegramAuthConfigError,
    TelegramAuthError,
    verify_init_data,
)

# ─── Password hashing (admin) ─────────────────────────────────────────────────
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ─── Telegram initData verification ──────────────────────────────────────────
def verify_telegram_init_data(init_data: str, max_age_seconds: int | None = None) -> dict:
    """
    Verify Telegram Mini App initData (official HMAC-SHA256 algorithm).
    Returns the Telegram user dict (+ start_param) on success.

    Raises TelegramAuthError (a ValueError) if the data is invalid/expired, or
    TelegramAuthConfigError if the server has no bot token. The implementation
    lives in app.core.telegram_auth (stdlib only, unit-tested with real HMAC).
    """
    if max_age_seconds is None:
        max_age_seconds = settings.TELEGRAM_AUTH_MAX_AGE_SECONDS
    return verify_init_data(
        init_data,
        settings.TELEGRAM_BOT_TOKEN,
        max_age_seconds=max_age_seconds,
    )


# ─── JWT (RS256) ─────────────────────────────────────────────────────────────
def _load_key(path: str) -> str:
    p = Path(path)
    if p.exists():
        return p.read_text()
    kind = "jwt_private" if path == settings.JWT_PRIVATE_KEY_PATH else "jwt_public"
    auto = auto_secrets.get(kind)
    if not auto:
        raise FileNotFoundError(f"Key file not found: {path}")
    return auto


def create_access_token(user_id: str) -> str:
    private_key = _load_key(settings.JWT_PRIVATE_KEY_PATH)
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.JWT_ACCESS_TOKEN_EXPIRE_HOURS
    )
    payload = {
        "sub": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, private_key, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Returns user_id (sub) or raises JWTError."""
    public_key = _load_key(settings.JWT_PUBLIC_KEY_PATH)
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[settings.JWT_ALGORITHM],
            # A token without an expiry must never be accepted.
            options={"require_exp": True, "require_iat": True},
        )
        # Only user access tokens are valid here. Admin tokens (role=admin,
        # type=admin_access) must never authenticate as a normal user.
        if payload.get("type") != "access" or payload.get("role") == "admin":
            raise JWTError("Wrong token type")
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise JWTError("Missing sub")
        return user_id
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")


ADMIN_TOKEN_EXPIRE_MINUTES = 60


def create_admin_token(username: str, token_version: int = 0) -> str:
    """
    Short-lived admin JWT (role=admin, type=admin_access).
    The token only identifies the admin; the admin's ROLE is always read from
    the database on every request (see core.deps), so a role change or a
    disabled account takes effect immediately. `tv` lets a password change /
    disable revoke tokens that were already issued.
    """
    private_key = _load_key(settings.JWT_PRIVATE_KEY_PATH)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": "admin",
        "type": "admin_access",
        "tv": int(token_version),
        "iat": now,
        "exp": now + timedelta(minutes=ADMIN_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, private_key, algorithm=settings.JWT_ALGORITHM)


def decode_admin_claims(token: str) -> dict:
    """Returns the verified admin claims or raises ValueError."""
    public_key = _load_key(settings.JWT_PUBLIC_KEY_PATH)
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True, "require_iat": True},
        )
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")
    if payload.get("role") != "admin" or payload.get("type") != "admin_access":
        raise ValueError("Not an admin token")
    if not isinstance(payload.get("sub"), str) or not payload["sub"]:
        raise ValueError("Missing sub")
    return payload


def decode_admin_token(token: str) -> str:
    """Returns admin username or raises ValueError."""
    return decode_admin_claims(token)["sub"]


# ─── Source URL encryption (Fernet/AES-128-CBC) ──────────────────────────────
def _fernet() -> Fernet:
    key = settings.SOURCE_URL_ENCRYPTION_KEY or auto_secrets.get("fernet")
    if not key:
        raise RuntimeError("Encryption key not ready")
    return Fernet(key.encode())


def encrypt_url(url: str) -> str:
    """Encrypt source URL for storage in Firestore."""
    return _fernet().encrypt(url.encode()).decode()


def decrypt_url(encrypted: str) -> str:
    """Decrypt source URL for authorized access only."""
    return _fernet().decrypt(encrypted.encode()).decode()
