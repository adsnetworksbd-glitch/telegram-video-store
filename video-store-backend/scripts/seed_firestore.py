"""
Firestore seed script.
Run once after Firebase setup to create initial documents.
Usage: python scripts/seed_firestore.py

Requires FIREBASE_SERVICE_ACCOUNT_PATH and FIREBASE_PROJECT_ID in .env
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.firebase import init_firebase, get_db, Col
from datetime import datetime, timezone


async def seed():
    init_firebase()
    db = get_db()

    # ── App Settings ────────────────────────────────────────────────────────
    print("Creating app_settings/config ...")
    await db.collection(Col.APP_SETTINGS).document("config").set({
        "app_name": "Video Store",
        "app_logo_url": None,
        "maintenance_mode": False,
        "maintenance_message": "আমরা রক্ষণাবেক্ষণ কাজ করছি। একটু পরে আসুন।",
        "currency_display": "BDT",
        "usdt_to_bdt_rate": 115.0,
        "payment_verify_min_interval_seconds": 5,   # min gap between Binance order queries per payment
        "payment_retry_limit_24h": 5,               # failed/expired orders per item per 24h before retry is blocked
        "referral_enabled": True,
        "referral_reward_type": "coupon",
        "referral_reward_amount": 100.0,
        "referral_fraud_cooldown_hours": 48,
        "referral_min_purchase_required": True,
        "wallet_enabled": False,
        "homepage_announcement": None,
        "homepage_announcement_url": None,
        "telegram_bot_username": "videostore_bot",
        "homepage_sections": [
            {"id": "featured_banner",    "label": "Featured Banner",   "enabled": True, "order": 1},
            {"id": "featured_videos",    "label": "Featured Videos",   "enabled": True, "order": 2},
            {"id": "trending_videos",    "label": "Trending Videos",   "enabled": True, "order": 3},
            {"id": "latest_videos",      "label": "Latest Videos",     "enabled": True, "order": 4},
            {"id": "popular_categories", "label": "Categories",        "enabled": True, "order": 5},
            {"id": "featured_packages",  "label": "Featured Packages", "enabled": True, "order": 6},
        ],
        "default_ads_required": 3,
        "default_ads_unlock_duration_hours": 24,
        "updated_at": datetime.now(timezone.utc),
    }, merge=True)

    # ── Payment Methods ──────────────────────────────────────────────────────
    print("Creating payment_methods ...")
    # Phase 10: deterministic IDs (safe to re-run) + new additive fields.
    # Replace every placeholder wallet / Pay ID below via the admin API before
    # enabling — placeholders are hidden from users (they fail address checks).
    _common = {"qr_code_url": None, "min_amount_usdt": 0.5, "max_amount_usdt": None,
               "merchant_name": None, "currency": "USDT", "manual_review_supported": True}
    methods = {
        "binance_pay": {**_common, "name": "Binance Pay", "type": "binance_pay", "is_enabled": True,
            "display_order": 1, "wallet_address": None, "pay_id": None, "network_name": None,
            "payment_timeout_minutes": 30, "auto_verification_supported": True,
            "instructions_text": "Binance Pay ব্যবহার করে পরিশোধ করুন। Payment করার পর স্বয়ংক্রিয়ভাবে যাচাই হবে।"},
        "binance_id": {**_common, "name": "Binance ID / Pay ID", "type": "binance_id", "is_enabled": False,
            "display_order": 2, "wallet_address": None, "pay_id": "000000000",
            "network_name": "Binance Internal", "payment_timeout_minutes": 60,
            "auto_verification_supported": False,
            "instructions_text": "Binance App থেকে উপরের Pay ID-তে হুবহু পরিমাণ পাঠান। এরপর Transaction/Order ID জমা দিন।"},
        "usdt_trc20": {**_common, "name": "USDT TRC20", "type": "usdt_trc20", "is_enabled": False,
            "display_order": 3, "wallet_address": "TYour_TRC20_Wallet_Address_Here", "pay_id": None,
            "network_name": "TRON (TRC20)", "payment_timeout_minutes": 60,
            "auto_verification_supported": False,
            "instructions_text": "TRON (TRC20) নেটওয়ার্কে USDT পাঠান। Transaction Hash জমা দিন।"},
        "usdt_bep20": {**_common, "name": "USDT BEP20", "type": "usdt_bep20", "is_enabled": False,
            "display_order": 4, "wallet_address": "0xYour_BEP20_Wallet_Address_Here", "pay_id": None,
            "network_name": "BSC (BEP20)", "payment_timeout_minutes": 60,
            "auto_verification_supported": False,
            "instructions_text": "BSC (BEP20) নেটওয়ার্কে USDT পাঠান। Transaction Hash জমা দিন।"},
        "usdt_erc20": {**_common, "name": "USDT ERC20", "type": "usdt_erc20", "is_enabled": False,
            "display_order": 5, "wallet_address": "0xYour_ERC20_Wallet_Address_Here", "pay_id": None,
            "network_name": "Ethereum (ERC20)", "payment_timeout_minutes": 90,
            "min_amount_usdt": 5.0, "auto_verification_supported": False,
            "instructions_text": "Ethereum (ERC20) নেটওয়ার্কে USDT পাঠান (Gas Fee বেশি হতে পারে)। Transaction Hash জমা দিন।"},
    }
    for mid, m in methods.items():
        ref = db.collection(Col.PAYMENT_METHODS).document(mid)
        if (await ref.get()).exists:      # never overwrite what the admin configured
            print(f"  - {mid}: exists, skipped")
            continue
        await ref.set(m)

    # ── Ad Network ───────────────────────────────────────────────────────────
    print("Creating ad_networks/monetag ...")
    await db.collection(Col.AD_NETWORKS).document("monetag").set({
        "name": "Monetag",
        "type": "monetag",
        "is_enabled": False,  # Enable after getting Monetag credentials
        "priority": 1,
        "publisher_id_ref": None,
        "zone_id": None,
        "s2s_callback_supported": True,
        "s2s_callback_secret_ref": "MONETAG_CALLBACK_SECRET",
        "default_ads_required": 3,
        "unlock_duration_hours": 24,
        "placements": {"video_unlock": True, "package_unlock": True},
        "session_timeout_minutes": 30,
        "sdk_url": None,   # set from admin API (https only) once Monetag gives you the SDK URL
        "display_order": 1,
    }, merge=True)

    # ── Sample FAQ ───────────────────────────────────────────────────────────
    print("Creating FAQ entries ...")
    faqs = [
        {"question": "Payment কিভাবে করব?", "answer": "Binance Pay বা USDT (TRC20/BEP20) দিয়ে Payment করা যায়। Payment page-এ বিস্তারিত দেওয়া আছে।", "display_order": 1, "is_visible": True},
        {"question": "Video কাজ না করলে কী করব?", "answer": "Support Ticket পাঠান। ২৪ ঘণ্টার মধ্যে সমাধান করা হবে।", "display_order": 2, "is_visible": True},
        {"question": "Ads দেখার পর Unlock না হলে?", "answer": "কখনো কখনো যাচাই একটু সময় নিতে পারে। ৫ মিনিট অপেক্ষা করুন। তারপরও না হলে Support-এ যোগাযোগ করুন।", "display_order": 3, "is_visible": True},
        {"question": "Referral Reward কখন পাব?", "answer": "যাকে Refer করেছেন সে প্রথম Purchase করলে Reward পাবেন।", "display_order": 4, "is_visible": True},
    ]
    for faq in faqs:
        await db.collection(Col.FAQ).add(faq)

    print("\n✅ Firestore seed completed!")
    print("\nপরবর্তী পদক্ষেপ:")
    print("1. Firebase Console → Firestore → Indexes তৈরি করুন (নিচের indexes.md দেখুন)")
    print("2. Admin Panel দিয়ে ভিডিও ও ক্যাটাগরি যোগ করুন")
    print("3. Payment method-এর wallet address আপডেট করুন")
    print("4. Monetag credentials পেলে ad_networks/monetag আপডেট করুন")


if __name__ == "__main__":
    asyncio.run(seed())
