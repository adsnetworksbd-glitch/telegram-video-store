# Firestore Composite Indexes

> **Phase 7 update:** the table below was incomplete — several live queries
> (plain video list/popular, categories, packages list, payment methods, ad
> networks, FAQ) had no matching index and would fail with `FAILED_PRECONDITION`
> (HTTP 500) on a real Firestore. The complete, query-derived set is now in
> **`firestore.indexes.json`** (36 indexes). Deploy it (config only — no data
> migration, no new collection):
> ```bash
> firebase deploy --only firestore:indexes
> ```
> Not yet verified against a live Firestore. Tables below are the older partial list.

Firebase Console → Firestore Database → Indexes → Composite → Add Index

## Required Indexes

### videos
| Collection | Fields | Query Scope |
|---|---|---|
| videos | is_published ASC, is_featured ASC, created_at DESC | Collection |
| videos | is_published ASC, is_trending ASC, view_count DESC | Collection |
| videos | is_published ASC, category_ids ARRAY, created_at DESC | Collection |
| videos | is_published ASC, category_ids ARRAY, view_count DESC | Collection |

### entitlements
| Collection | Fields | Query Scope |
|---|---|---|
| entitlements | user_id ASC, content_type ASC, content_id ASC, status ASC | Collection |
| entitlements | user_id ASC, content_type ASC, status ASC, created_at DESC | Collection |
| entitlements | user_id ASC, content_type ASC, included_video_ids ARRAY, status ASC | Collection |
| entitlements | user_id ASC, created_at DESC | Collection |  <!-- GET /entitlements (status filtered in app code) -->
| entitlements | user_id ASC, content_type ASC, created_at DESC | Collection |

### orders
| Collection | Fields | Query Scope |
|---|---|---|
| orders | user_id ASC, status ASC, created_at DESC | Collection |
| orders | user_id ASC, created_at DESC | Collection |

### payments
| Collection | Fields | Query Scope |
|---|---|---|
| payments | order_id ASC, created_at DESC | Collection |

### ad_unlock_sessions
| Collection | Fields | Query Scope |
|---|---|---|
| ad_unlock_sessions | user_id ASC, content_id ASC, is_complete ASC | Collection |

### transactions
| Collection | Fields | Query Scope |
|---|---|---|
| transactions | user_id ASC, type ASC, created_at DESC | Collection |
| transactions | user_id ASC, created_at DESC | Collection |

### notifications
| Collection | Fields | Query Scope |
|---|---|---|
| notifications | user_id ASC, is_read ASC, created_at DESC | Collection |
| notifications | user_id ASC, created_at DESC | Collection |

### referrals
| Collection | Fields | Query Scope |
|---|---|---|
| referrals | referrer_user_id ASC, created_at DESC | Collection |
| referrals | referred_user_id ASC, status ASC | Collection |

### coupon_usage
| Collection | Fields | Query Scope |
|---|---|---|
| coupon_usage | coupon_id ASC, user_id ASC | Collection |
| coupon_usage | order_id ASC | Collection |

### packages
| Collection | Fields | Query Scope |
|---|---|---|
| packages | is_published ASC, is_featured ASC, display_order ASC | Collection |

---

## Firestore Security Rules

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // সব Write শুধু Backend Admin SDK
    // Frontend Firestore সরাসরি access করে না
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

Deploy করুন:
```bash
firebase deploy --only firestore:rules
```


## Render deployment note (key files)
`private.pem`, `public.pem` and `firebase-service-account.json` are git-ignored, so they do not exist on Render.
Upload them as **Render Secret Files** (mounted at `/etc/secrets/<name>`) and set
`JWT_PRIVATE_KEY_PATH=/etc/secrets/private.pem`, `JWT_PUBLIC_KEY_PATH=/etc/secrets/public.pem`,
`FIREBASE_SERVICE_ACCOUNT_PATH=/etc/secrets/firebase-service-account.json`.
Production startup now REFUSES to boot if these files are missing (validate_runtime_config).
