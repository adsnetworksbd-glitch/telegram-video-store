# Video Store — Backend

FastAPI + Firebase Firestore | Python 3.11+

## Quick Start

```bash
pip install -r requirements.txt
python scripts/generate_keys.py      # RSA keys
cp .env.example .env                 # Fill in values
python scripts/seed_firestore.py     # Initial Firestore data
uvicorn app.main:app --reload        # Start server
# API Docs: http://localhost:8000/docs
```

## Setup Checklist

- [ ] Firebase project তৈরি, `firebase-service-account.json` download
- [ ] `python scripts/generate_keys.py` → `private.pem`, `public.pem`
- [ ] `.env` সব values পূরণ
- [ ] Firestore indexes তৈরি (`docs/firestore_indexes.md`)
- [ ] `python scripts/seed_firestore.py`
- [ ] Render deploy (`docs/deployment_guide.md`)
- [ ] UptimeRobot দিয়ে `/health` ping (১৪ মিনিট interval)

## Project Structure

```
app/
├── api/v1/endpoints/   # auth, config, videos, packages, orders, ads, misc
├── bot/                # Telegram Bot (aiogram, background task)
├── core/               # config, security, deps
├── db/                 # Firebase connection, collection names
├── schemas/            # Pydantic models (Frontend-compatible)
├── services/           # entitlement, coupon, referral, binance, fulfillment
└── utils/              # audit, notifications
scripts/
├── generate_keys.py    # RSA key pair
└── seed_firestore.py   # Initial data
docs/
├── api_reference.md    # All API endpoints
├── firestore_indexes.md
└── deployment_guide.md
```

## API Base URL
`https://your-backend.onrender.com/api/v1`

## Security
- Telegram initData HMAC-SHA256 verified
- JWT RS256 asymmetric signing
- Source URL Fernet encrypted at rest
- Binance webhook HMAC-SHA512 verified
- Monetag S2S HMAC-SHA256 verified
- Ad access: S2S callback only (never frontend-only)
- All secrets in Render environment variables
