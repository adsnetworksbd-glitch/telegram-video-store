# সম্পূর্ণ Setup গাইড — ধাপে ধাপে

## ধাপ ১: GitHub Repository তৈরি

```bash
# Frontend
cd video-store-frontend
git init && git add . && git commit -m "init frontend"
git remote add origin https://github.com/YOUR/video-store-frontend.git
git push -u origin main

# Backend
cd video-store-backend
git init && git add . && git commit -m "init backend"
git remote add origin https://github.com/YOUR/video-store-backend.git
git push -u origin main
```

## ধাপ ২: Firebase Setup

1. firebase.google.com → Add project
2. Firestore Database → Create → Production mode
3. Project Settings → Service accounts → Generate new private key
4. JSON ফাইল save করুন (backend-এ লাগবে)
5. Firebase Console → Firestore → Indexes → `docs/firestore_indexes.md` অনুযায়ী তৈরি করুন

## ধাপ ৩: Backend (Render) Deploy

1. render.com → New Web Service → GitHub connect
2. Build: `pip install -r requirements.txt`
3. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Environment Variables যোগ করুন (`.env.example` দেখুন)
5. Secret Files:
   - `/etc/secrets/firebase-service-account.json`
   - `/etc/secrets/private.pem`
   - `/etc/secrets/public.pem`

## ধাপ ৪: Firestore Seed

```bash
# Local-এ একবার চালান
FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-service-account.json \
FIREBASE_PROJECT_ID=your-project-id \
python scripts/seed_firestore.py
```

## ধাপ ৫: Frontend (Vercel) Deploy

1. vercel.com → New Project → GitHub connect
2. Environment Variable:
   - `VITE_API_URL` = `https://your-backend.onrender.com/api/v1`
3. Deploy

## ধাপ ৬: Telegram Bot Setup

1. @BotFather → /newbot → Token পান
2. Render-এ `TELEGRAM_BOT_TOKEN` সেট করুন
3. `app/bot/main.py`-এ `mini_app_url` = Vercel URL দিন
4. Redeploy

## ধাপ ৭: Mini App Register

1. @BotFather → /newapp → Bot select
2. Web App URL = Vercel URL দিন
3. টেলিগ্রামে bot খুলুন → "Video Store খুলুন" বোতাম দেখবেন

## ধাপ ৮: UptimeRobot (Sleep prevent)

1. uptimerobot.com → Free account
2. New Monitor → HTTP(s)
3. URL: `https://your-backend.onrender.com/health`
4. Interval: 14 minutes

## ধাপ ৯: প্রথম ভিডিও যোগ

Firebase Console → Firestore → videos collection → Add document:
```json
{
  "title": "Test Video",
  "slug": "test-video",
  "thumbnail_url": "https://...",
  "category_ids": ["cat_id"],
  "primary_category_id": "cat_id",
  "quality": "HD",
  "duration_seconds": 3600,
  "file_size_mb": 1000,
  "source_type": "custom_url",
  "source_url_encrypted": "[Fernet encrypted URL]",
  "price_bdt": 100,
  "is_free": false,
  "is_featured": true,
  "is_trending": false,
  "is_latest": true,
  "is_published": true,
  "ads_unlock_enabled": true,
  "purchase_enabled": true,
  "ads_required": 3,
  "ads_unlock_duration_hours": 24,
  "purchase_duration_hours": 0,
  "view_count": 0,
  "purchase_count": 0,
  "created_at": "[timestamp]"
}
```

**Source URL Encrypt করতে:**
```python
from cryptography.fernet import Fernet
f = Fernet(b"your-key")
print(f.encrypt(b"https://your-video-url.com").decode())
```

## ✅ সম্পন্ন!

Telegram-এ bot খুলুন → Mini App দেখুন।
