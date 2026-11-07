# Video Store — Frontend

Telegram Mini App | React + TypeScript + Tailwind CSS + Framer Motion

## Quick Start

```bash
npm install
cp .env.example .env.local
# VITE_API_URL খালি রাখলে Dev-এ http://localhost:8000/api/v1 ব্যবহৃত হয়
npm run dev
```

## Production Deploy (Vercel)

1. GitHub-এ push করুন
2. vercel.com → Import repository
3. Environment Variables:
   - `VITE_API_URL` = `https://your-backend.onrender.com/api/v1`
4. Deploy

> **Production Build-এ `VITE_API_URL` বাধ্যতামূলক।** কোনো Hard-coded Fallback নেই (JWT ভুল Host-এ যাওয়া ঠেকাতে)। না দিলে বা নমুনা মান (`your-backend…`) থাকলে App শুরুতেই পরিষ্কার ত্রুটি দেখায়।

## Project Structure

```
src/
├── api/          # All API service functions
├── components/   # Reusable UI, Video, Package, Layout, Access components
├── pages/        # 19 pages (Home, VideoDetail, Purchase, Payment, etc.)
├── store/        # Zustand state (Auth, User, Config)
├── hooks/        # useTelegram, useVideoAccess, etc.
├── types/        # TypeScript types (matches Backend schemas)
└── utils/        # Currency, duration, date, source handler
```

## Pages

| Route | Page |
|---|---|
| `/` | Home |
| `/videos` | All Videos |
| `/videos/:id` | Video Detail |
| `/videos/:id/watch-ads` | Watch Ads |
| `/videos/:id/ads-success` | Ads Success |
| `/videos/:id/purchase` | Purchase |
| `/categories` | Categories |
| `/categories/:id` | Category Detail |
| `/packages` | Packages |
| `/packages/:id` | Package Detail |
| `/payment/:orderId` | Payment |
| `/payment/:orderId/pending` | Payment Pending |
| `/payment/:orderId/success` | Payment Success |
| `/payment/:orderId/failed` | Payment Failed |
| `/my-purchases` | My Purchases |
| `/account` | Account |
| `/transactions` | Transactions |
| `/search` | Search |
| `/support` | Support |
