"""Pydantic v2 schemas — match Frontend TypeScript types exactly."""
from __future__ import annotations
import re
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Common ───────────────────────────────────────────────────────────────────
class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    has_more: bool


# ─── Auth ─────────────────────────────────────────────────────────────────────
class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=4096)
    # Referral code from the Mini App launch URL (?startapp=VS-XXXXXXX). Telegram only puts
    # `start_param` into initData for direct-link launches, NOT for the bot's web_app button,
    # so the frontend forwards it. It is only a referral attribution hint (never an identity):
    # the user id always comes from the verified initData.
    start_param: str | None = Field(default=None, max_length=16, pattern=r"^VS-[A-Z0-9]{7}$")


class TokenResponse(BaseModel):
    access_token: str
    user: "UserProfile"


# ─── User ─────────────────────────────────────────────────────────────────────
class UserProfile(BaseModel):
    telegram_id: str
    username: str | None
    first_name: str
    last_name: str | None
    photo_url: str | None
    referral_code: str
    referral_count: int
    referral_reward_total_bdt: float
    total_spent_bdt: float
    wallet_balance: float = 0.0
    wallet_enabled: bool = False
    is_banned: bool
    created_at: datetime
    last_seen_at: datetime


# ─── App Config ───────────────────────────────────────────────────────────────
class HomepageSection(BaseModel):
    id: str
    label: str
    enabled: bool
    order: int


class AppConfig(BaseModel):
    app_name: str
    app_logo_url: str | None
    maintenance_mode: bool
    maintenance_message: str
    currency_display: str
    usdt_to_bdt_rate: float
    referral_enabled: bool
    wallet_enabled: bool
    homepage_announcement: str | None
    homepage_announcement_url: str | None
    # Optional admin-controlled links (same app_settings/config document).
    # Additive: older clients ignore them; the Support page shows "not set" when null.
    terms_url: str | None = None
    privacy_url: str | None = None
    support_username: str | None = None
    support_url: str | None = None


class HomepageBanner(BaseModel):
    """Admin-managed banner (Phase 12 / 1C). Only enabled banners inside their date window are served."""
    id: str
    title: str | None = None
    image_url: str
    link_type: Literal["none", "video", "package", "url"] = "none"
    link_id: str | None = None
    link_url: str | None = None
    order: int = 0


class HomepageConfig(BaseModel):
    sections: list[HomepageSection]
    banners: list[HomepageBanner] = []     # additive: older clients ignore it


# ─── Video ────────────────────────────────────────────────────────────────────
VideoQuality = Literal["SD", "HD", "FHD", "4K"]
SourceType = Literal[
    "telegram_bot", "telegram_channel",
    "google_drive", "dropbox",
    "direct_mp4", "custom_url",
]


class Video(BaseModel):
    id: str
    title: str
    slug: str
    thumbnail_url: str
    category_ids: list[str]
    primary_category_id: str
    quality: VideoQuality
    duration_seconds: int
    file_size_mb: float
    price_bdt: float
    is_free: bool
    is_featured: bool
    is_trending: bool
    is_latest: bool
    ads_unlock_enabled: bool
    purchase_enabled: bool
    ads_required: int
    ads_unlock_duration_hours: int
    purchase_duration_hours: int
    view_count: int
    purchase_count: int
    created_at: datetime


class AccessStatus(BaseModel):
    granted: bool
    source: str | None
    expires_at: datetime | None
    is_lifetime: bool
    # True when the user HAD temporary access that has now run out
    # (drives the "Expired" badge; default keeps older callers valid).
    expired: bool = False
    # Every access source that is valid right now (best first), e.g.
    # ["individual_purchase", "ads_unlock"]. `source` is the best one. Each is a
    # separate record; default [] keeps older callers valid.
    active_sources: list[str] = []


class AvailableMethods(BaseModel):
    ads_unlock: bool
    purchase: bool
    is_free: bool


class VideoDetail(Video):
    description: str
    source_type: SourceType
    access: AccessStatus
    available_methods: AvailableMethods


class VideoListResponse(BaseModel):
    items: list[Video]
    total: int
    page: int
    has_more: bool


# ─── Category ─────────────────────────────────────────────────────────────────
class Category(BaseModel):
    id: str
    name: str
    slug: str
    thumbnail_url: str
    description: str | None
    video_count: int
    display_order: int


class CategoryListResponse(BaseModel):
    categories: list[Category]


class CategoryDetailResponse(BaseModel):
    category: Category
    videos: list[Video]
    total: int


# ─── Package ──────────────────────────────────────────────────────────────────
class Package(BaseModel):
    id: str
    name: str
    thumbnail_url: str
    description: str
    video_ids: list[str]
    video_count: int
    price_bdt: float
    original_price_bdt: float
    discount_percentage: float
    ads_unlock_enabled: bool
    purchase_enabled: bool
    duration_type: Literal["lifetime", "custom"]
    duration_hours: int
    ads_required: int
    is_featured: bool
    purchase_count: int
    created_at: datetime


class PackageDetail(Package):
    included_videos: list[Video]
    access: AccessStatus
    available_methods: AvailableMethods


class PackageListResponse(BaseModel):
    items: list[Package]
    total: int
    page: int
    has_more: bool


# ─── Source Access ────────────────────────────────────────────────────────────
class SourceAccess(BaseModel):
    source_type: SourceType
    redirect_url: str


# ─── Entitlement ──────────────────────────────────────────────────────────────
AccessSource = Literal[
    "free", "ads_unlock", "individual_purchase",
    "package_purchase", "admin_grant",
]
EntitlementStatus = Literal["active", "expired", "revoked"]


class Entitlement(BaseModel):
    id: str
    user_id: str
    content_type: Literal["video", "package"]
    content_id: str
    included_video_ids: list[str]
    access_source: AccessSource
    order_id: str | None
    ad_unlock_session_id: str | None
    start_at: datetime
    expires_at: datetime | None
    is_lifetime: bool
    status: EntitlementStatus
    created_at: datetime
    video: Video | None = None
    package: Package | None = None


class EntitlementListResponse(BaseModel):
    items: list[Entitlement]
    total: int
    page: int
    has_more: bool


# ─── Order ────────────────────────────────────────────────────────────────────
OrderStatus = Literal[
    "pending", "awaiting_payment", "payment_submitted",
    "under_review", "completed", "failed", "refunded", "expired",
]


class OrderCreateRequest(BaseModel):
    content_type: Literal["video", "package"]
    content_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payment_method_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    coupon_code: str | None = Field(default=None, max_length=64)


class PaymentDetails(BaseModel):
    payment_id: str
    method: str
    expected_usdt: float
    wallet_address: str | None
    network: str | None
    qr_code_url: str | None
    binance_checkout_url: str | None
    instructions_text: str
    expires_at: datetime
    # Phase 10 (additive): everything the payment screen needs, from the Backend.
    method_name: str = ""
    currency: str = "USDT"
    pay_id: str | None = None
    merchant_name: str | None = None
    auto_verification_supported: bool = False
    manual_review_supported: bool = True
    reused: bool = False   # True when an existing open order was returned (duplicate prevention)


class OrderCreateResponse(BaseModel):
    order_id: str
    final_bdt: float
    final_usdt: float
    usdt_rate: float
    expires_at: datetime
    payment_details: PaymentDetails


class Order(BaseModel):
    id: str
    user_id: str
    content_type: str
    content_id: str
    amount_bdt: float
    coupon_code: str | None
    discount_bdt: float
    final_bdt: float
    final_usdt: float
    usdt_rate_at_creation: float
    payment_method_id: str
    status: OrderStatus
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    currency: str = "USDT"   # Phase 10 (additive)
    payment_method_type: str | None = None   # Phase 10 Part 2B (additive): history list can name the method


class Payment(BaseModel):
    id: str
    order_id: str
    payment_method: str
    expected_usdt: float
    paid_amount_usdt: float | None
    binance_checkout_url: str | None
    wallet_address: str | None
    network: str | None
    verification_method: str
    verification_status: str
    created_at: datetime
    # Phase 10 Part 2B (additive, all user-safe — never admin notes / names)
    review_code: str | None = None        # why it waits for an admin (see services/order_view.py)
    attempts: int = 0                     # Binance status checks so far
    last_checked_at: datetime | None = None
    pay_id: str | None = None


class TimelineEvent(BaseModel):
    at: datetime
    step: str
    source: str


class RetryInfo(BaseModel):
    allowed: bool = False
    remaining: int | None = None


class OrderDetailResponse(BaseModel):
    order: Order
    payment: Payment
    # Phase 10 Part 2B (additive): the admin-configured screen data, from the
    # backend (order snapshot + method document) — the frontend hardcodes none of it.
    details: PaymentDetails | None = None
    timeline: list[TimelineEvent] = []
    retry: RetryInfo = RetryInfo()


class PaymentSubmitRequest(BaseModel):
    transaction_hash: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9x]+$")
    screenshot_url: str | None = Field(default=None, max_length=1000, pattern=r"^https://")
    user_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _need_proof(self):
        if not (self.transaction_hash or self.screenshot_url):
            raise ValueError("transaction_hash or screenshot_url is required")
        return self


class PaymentSubmitResponse(BaseModel):
    status: OrderStatus
    message: str


class PaymentVerifyResponse(BaseModel):
    """Result of POST /orders/{id}/verify (Phase 10 Part 2A). Status is the ORDER's real state."""
    status: OrderStatus
    outcome: str            # fulfilled | review | failed | wait | noop | manual
    message: str
    entitlement_id: str | None = None


class OrderRetryRequest(BaseModel):
    """Optional: pay the retried order with a different method."""
    payment_method_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


# ─── Payment Methods ──────────────────────────────────────────────────────────
class PaymentMethod(BaseModel):
    id: str
    name: str
    type: str
    is_enabled: bool
    display_order: int
    wallet_address: str | None
    network_name: str | None
    qr_code_url: str | None
    min_amount_usdt: float
    max_amount_usdt: float | None
    payment_timeout_minutes: int
    instructions_text: str
    auto_verification_supported: bool
    # Phase 10 (additive)
    kind: str = "custom"
    pay_id: str | None = None
    merchant_name: str | None = None
    currency: str = "USDT"
    manual_review_supported: bool = True


class PaymentMethodListResponse(BaseModel):
    methods: list[PaymentMethod]


# ─── Ad Session ───────────────────────────────────────────────────────────────
class AdNetworkConfig(BaseModel):
    network_id: str
    zone_id: str | None
    type: str
    # Additive (Phase 9): public, non-secret provider info for the client.
    provider_id: str | None = None
    sdk_url: str | None = None


class AdSessionStartRequest(BaseModel):
    content_type: Literal["video", "package"]
    content_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class AdSession(BaseModel):
    session_id: str
    server_token: str
    ads_required: int
    ads_completed: int
    s2s_verified_count: int
    is_complete: bool
    network_config: AdNetworkConfig
    expires_at: datetime
    entitlement_id: str | None
    # Additive (Phase 9): pending | in_progress | completed | expired
    status: str | None = None
    placement: str | None = None


class AdSessionCompleteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    server_token: str = Field(min_length=1, max_length=128)


# ─── Coupon ───────────────────────────────────────────────────────────────────
class CouponValidateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    content_type: Literal["video", "package"]
    content_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    order_amount_bdt: float = Field(ge=0, le=10_000_000)


class CouponValidation(BaseModel):
    valid: bool
    discount_bdt: float
    final_bdt: float
    message: str


# ─── Referral ─────────────────────────────────────────────────────────────────
class ReferralInfo(BaseModel):
    referral_code: str
    referral_count: int
    reward_total_bdt: float
    referral_link: str


class Referral(BaseModel):
    id: str
    referred_user_id: str
    status: str
    reward_type: str
    reward_amount_bdt: float | None
    created_at: datetime


class ReferralListResponse(BaseModel):
    items: list[Referral]
    total: int
    page: int
    has_more: bool


# ─── Transaction ──────────────────────────────────────────────────────────────
class Transaction(BaseModel):
    id: str
    type: str
    amount_bdt: float
    direction: Literal["credit", "debit"]
    reference_type: str
    reference_id: str
    description: str
    created_at: datetime


class TransactionListResponse(BaseModel):
    items: list[Transaction]
    total: int
    page: int
    has_more: bool


# ─── Notification ─────────────────────────────────────────────────────────────
class Notification(BaseModel):
    id: str
    type: str
    title: str
    body: str
    is_read: bool
    action_type: str | None
    action_id: str | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[Notification]
    unread_count: int


class MarkReadRequest(BaseModel):
    notification_ids: list[str] | Literal["all"]

    @field_validator("notification_ids")
    @classmethod
    def _cap_ids(cls, v):
        if isinstance(v, list):
            if len(v) > 100:
                raise ValueError("too many ids")
            # ids are used as Firestore document ids: no "/" or other path characters
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", i) for i in v):
                raise ValueError("invalid id")
        return v


# ─── Support ──────────────────────────────────────────────────────────────────
class FAQ(BaseModel):
    id: str
    question: str
    answer: str


class FAQListResponse(BaseModel):
    faqs: list[FAQ]


class SupportTicketRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="general", max_length=50)


class SupportTicketResponse(BaseModel):
    ticket_id: str


# ─── Search ───────────────────────────────────────────────────────────────────
class SearchResponse(BaseModel):
    videos: list[Video]
    packages: list[Package]
    total: int
