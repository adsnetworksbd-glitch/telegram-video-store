/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly VITE_DEV_MODE?: string
  /** Optional URL of the rewarded-ad SDK script (see utils/rewardedAd.ts). */
  readonly VITE_AD_SDK_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
