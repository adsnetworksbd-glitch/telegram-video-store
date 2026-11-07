"""
Auto-generated secrets (JWT key pair + source-URL encryption key).

So the only thing you must put in the environment is the admin login, these are
created on first start and kept in Firestore (doc `admin/auto_secrets`), so they
survive restarts/redeploys. Values set in env / key files still win.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)

_secrets: dict[str, str] = {}


def get(name: str) -> str:
    return _secrets.get(name, "")


def _generate() -> dict[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return {"jwt_private": private, "jwt_public": public, "fernet": Fernet.generate_key().decode()}


async def load_or_create(db) -> None:
    ref = db.collection("admin").document("auto_secrets")
    snap = await ref.get()
    data = (snap.to_dict() or {}) if snap.exists else {}
    if not all(data.get(k) for k in ("jwt_private", "jwt_public", "fernet")):
        data = {**data, **{k: v for k, v in _generate().items() if not data.get(k)}}
        await ref.set(data)
        logger.info("Auto secrets generated and stored ✓")
    _secrets.update({k: str(data[k]) for k in ("jwt_private", "jwt_public", "fernet")})
