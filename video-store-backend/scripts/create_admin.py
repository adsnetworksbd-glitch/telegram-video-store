"""
Create or update an admin account in Firestore (collection `admin_users`).

Usage (from video-store-backend/, with the same .env as the API):
  python scripts/create_admin.py create  <username> --role admin [--name "Rahim"]
  python scripts/create_admin.py update  <username> [--role moderator] [--name "..."] [--password]
  python scripts/create_admin.py disable <username>
  python scripts/create_admin.py enable  <username>

The password is always asked for interactively (never as an argument).
Changing the password / role or disabling an account also signs out its
existing sessions (token_version is bumped).
"""
import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.admin_roles import ROLES
from app.core.security import hash_password
from app.db.firebase import Col, get_db, init_firebase
from app.services.admin_auth import USERNAME_RE, normalize_username


def ask_password() -> str:
    while True:
        pw = getpass.getpass("Password (10-72 chars): ")
        if not 10 <= len(pw.encode()) <= 72:
            print("Password must be 10-72 bytes long.")
            continue
        if pw != getpass.getpass("Repeat password: "):
            print("Passwords do not match.")
            continue
        return pw


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["create", "update", "disable", "enable"])
    ap.add_argument("username")
    ap.add_argument("--role", choices=ROLES)
    ap.add_argument("--name", dest="display_name")
    ap.add_argument("--password", action="store_true", help="(update) set a new password")
    a = ap.parse_args()

    uname = normalize_username(a.username)
    if not USERNAME_RE.fullmatch(uname):
        print("Username: 3-32 chars, a-z 0-9 . _ - (must start with a letter or digit).")
        return 1

    init_firebase()
    ref = get_db().collection(Col.ADMIN_USERS).document(uname)
    snap = await ref.get()
    now = datetime.now(timezone.utc)

    if a.action == "create":
        if snap.exists:
            print(f"'{uname}' already exists — use 'update'.")
            return 1
        if not a.role:
            print("--role is required for create.")
            return 1
        await ref.set({
            "username": uname, "display_name": a.display_name or uname, "role": a.role,
            "password_hash": hash_password(ask_password()), "is_active": True,
            "token_version": 0, "failed_attempts": 0, "locked_until": None,
            "last_login_at": None, "created_at": now, "updated_at": now, "created_by": "cli",
        })
        print(f"Created {a.role} '{uname}'.")
        return 0

    if not snap.exists:
        print(f"'{uname}' not found.")
        return 1
    rec = snap.to_dict() or {}
    upd: dict = {"updated_at": now}
    revoke = False
    if a.action == "disable":
        upd["is_active"], revoke = False, True
    elif a.action == "enable":
        upd.update(is_active=True, failed_attempts=0, locked_until=None)
    else:
        if a.role and a.role != rec.get("role"):
            upd["role"], revoke = a.role, True
        if a.display_name:
            upd["display_name"] = a.display_name
        if a.password:
            upd["password_hash"], revoke = hash_password(ask_password()), True
            upd.update(failed_attempts=0, locked_until=None)
    if revoke:
        upd["token_version"] = int(rec.get("token_version") or 0) + 1
    await ref.update(upd)
    print(f"Updated '{uname}'" + (" (existing sessions signed out)." if revoke else "."))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
