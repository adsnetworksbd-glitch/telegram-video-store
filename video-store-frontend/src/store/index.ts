import { create } from 'zustand'
import type { UserProfile, AppConfig, HomepageSection, Notification, Category } from '@/types'

// ─── Auth Store ───────────────────────────────────────────────────────────────
interface AuthState {
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  setToken: (token: string) => void
  clearAuth: () => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,         // JWT stored in memory only — never localStorage
  isAuthenticated: false,
  isLoading: true,
  error: null,
  setToken: (token) => set({ token, isAuthenticated: true, isLoading: false, error: null }),
  clearAuth: () => set({ token: null, isAuthenticated: false }),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error, isLoading: false }),
}))

// ─── User Store ───────────────────────────────────────────────────────────────
interface UserState {
  profile: UserProfile | null
  notifications: Notification[]
  unreadCount: number
  setProfile: (p: UserProfile) => void
  setNotifications: (n: Notification[], unread: number) => void
  markNotificationsRead: () => void
}

export const useUserStore = create<UserState>((set) => ({
  profile: null,
  notifications: [],
  unreadCount: 0,
  setProfile: (profile) => set({ profile }),
  setNotifications: (notifications, unreadCount) => set({ notifications, unreadCount }),
  markNotificationsRead: () => set({ unreadCount: 0 }),
}))

// ─── Session reset ────────────────────────────────────────────────────────────
// Single place that ends a session (logout / expired / rejected): drops the JWT
// and every per-user object held in memory, so the next user/session never sees
// stale private data. Auth state is flipped FIRST (one atomic update) so the
// AuthGate unmounts the app before the user data is cleared.
export function resetSession(message: string | null = null): void {
  useAuthStore.setState({ token: null, isAuthenticated: false, isLoading: false, error: message })
  useUserStore.setState({ profile: null, notifications: [], unreadCount: 0 })
}

// ─── Config Store ─────────────────────────────────────────────────────────────
// appConfig / homepageSections / categories all come from the Backend (admin
// controlled). Nothing here is a hardcoded business value.
interface ConfigState {
  appConfig: AppConfig | null
  homepageSections: HomepageSection[]
  categories: Category[]
  isLoaded: boolean
  setAppConfig: (c: AppConfig) => void
  setHomepageSections: (s: HomepageSection[]) => void
  setCategories: (c: Category[]) => void
}

export const useConfigStore = create<ConfigState>((set) => ({
  appConfig: null,
  homepageSections: [],
  categories: [],
  isLoaded: false,
  setAppConfig: (appConfig) => set({ appConfig, isLoaded: true }),
  setHomepageSections: (homepageSections) => set({ homepageSections }),
  setCategories: (categories) => set({ categories }),
}))
