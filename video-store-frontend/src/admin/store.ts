import { create } from 'zustand'

export type AdminRole = 'super_admin' | 'admin' | 'moderator'

export interface AdminProfile {
  username: string
  display_name: string
  role: AdminRole
  permissions: string[]
}

export const ROLE_LABEL: Record<AdminRole, string> = {
  super_admin: 'Super Admin',
  admin: 'Admin',
  moderator: 'Moderator',
}

// The admin token lives in sessionStorage (per tab, gone when the tab closes,
// 60-minute server-side expiry), so a page reload does not force a new login.
// It is a separate key and a separate store from the Mini App user session.
const KEY = 'vs_admin_session'

interface Stored { token: string; expiresAt: number; admin: AdminProfile }

function load(): Stored | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as Partial<Stored>
    if (typeof s.token !== 'string' || typeof s.expiresAt !== 'number' || !s.admin) return null
    if (s.expiresAt <= Date.now()) { sessionStorage.removeItem(KEY); return null }
    return s as Stored
  } catch {
    return null
  }
}

function save(s: Stored | null) {
  try {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s))
    else sessionStorage.removeItem(KEY)
  } catch { /* storage unavailable: the session simply lasts until reload */ }
}

interface AdminAuthState {
  token: string | null
  expiresAt: number | null
  admin: AdminProfile | null
  setSession: (token: string, expiresInSeconds: number, admin: AdminProfile) => void
  setAdmin: (admin: AdminProfile) => void
  clear: () => void
}

const initial = load()

export const useAdminStore = create<AdminAuthState>((set, get) => ({
  token: initial?.token ?? null,
  expiresAt: initial?.expiresAt ?? null,
  admin: initial?.admin ?? null,
  setSession: (token, expiresInSeconds, admin) => {
    const expiresAt = Date.now() + expiresInSeconds * 1000
    save({ token, expiresAt, admin })
    set({ token, expiresAt, admin })
  },
  setAdmin: (admin) => {
    const { token, expiresAt } = get()
    if (token && expiresAt) save({ token, expiresAt, admin })
    set({ admin })
  },
  clear: () => {
    save(null)
    set({ token: null, expiresAt: null, admin: null })
  },
}))

/** UI-side permission check. Only a convenience: the server enforces every permission. */
export function can(admin: AdminProfile | null, permission: string): boolean {
  return !!admin && admin.permissions.includes(permission)
}
