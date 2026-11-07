"""
Firebase Admin SDK — singleton initializer.
All Firestore access goes through get_db().
Frontend never touches Firestore directly.
"""
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import AsyncClient
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_app: firebase_admin.App | None = None
_db: AsyncClient | None = None


def init_firebase() -> None:
    global _app, _db
    if _app is not None:
        return
    try:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        _app = firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
        _db = firestore.AsyncClient(project=settings.FIREBASE_PROJECT_ID)
        logger.info("Firebase initialized ✓")
    except Exception as e:
        logger.error(f"Firebase init failed: {e}")
        raise


def get_db() -> AsyncClient:
    if _db is None:
        raise RuntimeError("Firebase not initialized. Call init_firebase() first.")
    return _db


# ─── Collection name constants (single source of truth) ───────────────────────
class Col:
    APP_SETTINGS    = "app_settings"
    USERS           = "users"
    VIDEOS          = "videos"
    CATEGORIES      = "categories"
    PACKAGES        = "packages"
    ENTITLEMENTS    = "entitlements"
    ORDERS          = "orders"
    PAYMENTS        = "payments"
    PAYMENT_METHODS = "payment_methods"
    AD_NETWORKS     = "ad_networks"
    AD_SESSIONS     = "ad_unlock_sessions"
    COUPONS         = "coupons"
    COUPON_USAGE    = "coupon_usage"
    REFERRALS       = "referrals"
    TRANSACTIONS    = "transactions"
    NOTIFICATIONS   = "notifications"
    AUDIT_LOGS      = "audit_logs"
    ADMIN           = "admin"
    ADMIN_USERS     = "admin_users"
    SUPPORT_TICKETS = "support_tickets"
    FAQ             = "faq"
