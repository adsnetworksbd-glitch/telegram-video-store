"""
Audit logging — every important state change is recorded.
Notifications — async user notifications stored in Firestore.
"""
from datetime import datetime, timezone
from typing import Any
import uuid
import logging

from app.db.firebase import get_db, Col

logger = logging.getLogger(__name__)


async def audit_log(
    action: str,
    performed_by: str,
    target_type: str,
    target_id: str,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Fire-and-forget audit log. Never raises."""
    try:
        db = get_db()
        log_id = str(uuid.uuid4())
        await db.collection(Col.AUDIT_LOGS).document(log_id).set({
            "action": action,
            "performed_by": performed_by,
            "target_type": target_type,
            "target_id": target_id,
            "snapshot_before": before,
            "snapshot_after": after,
            "ip_address": ip,
            "user_agent": user_agent,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")


async def create_notification(
    user_id: str,
    type_: str,
    title: str,
    body: str,
    action_type: str | None = None,
    action_id: str | None = None,
) -> None:
    """Store notification in Firestore for the user."""
    try:
        db = get_db()
        notif_id = str(uuid.uuid4())
        await db.collection(Col.NOTIFICATIONS).document(notif_id).set({
            "user_id": user_id,
            "type": type_,
            "title": title,
            "body": body,
            "is_read": False,
            "action_type": action_type,
            "action_id": action_id,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning(f"Notification create failed: {e}")
