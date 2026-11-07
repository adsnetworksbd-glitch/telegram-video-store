# Deployment Guide — Video Store Backend

## প্রথমবার Setup (Local)

### ১. RSA Key তৈরি
```bash
pip install cryptography
python scripts/generate_keys.py
# private.pem এবং public.pem তৈরি হবে
```

### ২. Firebase Setup
1. Firebase Console → New Project তৈরি করুন
2. Firestore Database চালু করুন (Production mode)
3. Project Settings → Service Accounts → Generate new private key
4. Download করা JSON ফাইলটি `firebase-service-account.json` নামে রাখুন

### ৩. Environment Variables
```bash
cp .env.example .env
# .env ফাইলে সব values পূরণ করুন
```

### ৪. Fernet Key তৈরি (Source URL encryption)
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
# Output: .env-এর SOURCE_URL_ENCRYPTION_KEY-তে দিন
```

### ৫. Dependencies Install
```bash
pip install -r requirements.txt
```

### ৬. Firestore Seed
```bash
python scripts/seed_firestore.py
```

### ৭. Firestore Indexes তৈরি
`docs/firestore_indexes.md` দেখুন — Firebase Console-এ manually তৈরি করুন।

### ৮. Local Run
```bash
uvicorn app.main:app --reload --port 8000
# API Docs: http://localhost:8000/docs
```

---

## Render Deployment

### ১. GitHub-এ Push করুন
```bash
git init
git add .
git commit -m "Initial backend"
git remote add origin https://github.com/yourname/video-store-backend.git
git push -u origin main
```

### ২. Render-এ Service তৈরি
1. render.com → New → Web Service
2. GitHub repo connect করুন
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### ৩. Environment Variables (Render Dashboard)
Render → Environment → Add these secrets:
- `TELEGRAM_BOT_TOKEN`
- `FIREBASE_PROJECT_ID`
- `SOURCE_URL_ENCRYPTION_KEY`
- `BINANCE_PAY_API_KEY`
- `BINANCE_PAY_API_SECRET`
- `BINANCE_PAY_MERCHANT_ID`
- `MONETAG_CALLBACK_SECRET`
- `ALLOWED_ORIGINS` (Vercel frontend URL)
- `ADMIN_PASSWORD_HASH`

### ৪. Secret Files (Render Dashboard)
Render → Files → Add Secret File:
- `/etc/secrets/firebase-service-account.json` → Firebase service account JSON
- `/etc/secrets/private.pem` → RSA private key
- `/etc/secrets/public.pem` → RSA public key

তারপর `.env`-এ path আপডেট করুন:
```
FIREBASE_SERVICE_ACCOUNT_PATH=/etc/secrets/firebase-service-account.json
JWT_PRIVATE_KEY_PATH=/etc/secrets/private.pem
JWT_PUBLIC_KEY_PATH=/etc/secrets/public.pem
```

### ৫. UptimeRobot (Sleep prevent)
1. uptimerobot.com → Free account
2. New Monitor → HTTP(S)
3. URL: `https://your-backend.onrender.com/health`
4. Interval: ১৪ মিনিট

---

## Admin Panel (Phase 12 — সম্পন্ন)

Admin Panel একই Frontend-এর `/admin` রুটে এবং একই FastAPI Backend-এর `/api/v1/admin/*`-এ চলে।

1. Backend `.env`-এ `ADMIN_USERNAME` ও `ADMIN_PASSWORD_HASH` (bcrypt) সেট করুন — এটি Bootstrap Super Admin। (`python scripts/generate_keys.py`, `python scripts/create_admin.py` দেখুন।)
2. অন্য Admin/Moderator `/admin/admins` পেজ থেকে বা `scripts/create_admin.py` দিয়ে তৈরি করুন।
3. Binance API Key/Secret, Monetag callback secret ও JWT key শুধু Backend Environment-এ রাখুন; Frontend-এ কখনও নয়।
4. Frontend Deploy: `VITE_API_URL=https://<backend>/api/v1` সেট করে `npm run build`; `VITE_DEV_MODE` Production-এ `false`।
5. Deploy-এর আগে `firebase deploy --only firestore:rules,firestore:indexes` (Rules সব Client Access বন্ধ করে)।
6. Maintenance Mode: `/admin/settings` থেকে চালু করলে Mini App-এ Maintenance স্ক্রিন আসে এবং Backend নতুন Order / Ad Session (503) নেয় না; Admin Panel চালু থাকে।
7. Go-live চেকলিস্ট ও যা Live-এ যাচাই বাকি: `PHASE12_PART2C_NOTES.md`।
