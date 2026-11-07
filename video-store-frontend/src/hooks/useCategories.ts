import { categoriesApi } from '@/api'
import { useConfigStore } from '@/store'

// Video objects only carry category IDs. Category names come from the Backend
// once (single-flight) and are cached in the config store so every card can
// show a readable name instead of a raw ID.
let inflight: Promise<void> | null = null

export function ensureCategories(force = false): Promise<void> {
  const { categories, setCategories } = useConfigStore.getState()
  if (!force && categories.length > 0) return Promise.resolve()
  inflight ??= categoriesApi
    .list()
    .then((res) => setCategories(res.data.categories))
    .catch(() => { /* non-fatal: cards simply hide the category label */ })
    .finally(() => { inflight = null })
  return inflight
}

/** Returns the category name for an ID, or '' when unknown / not loaded yet. */
export function useCategoryName(id: string | null | undefined): string {
  return useConfigStore((s) => (id ? s.categories.find((c) => c.id === id)?.name ?? '' : ''))
}
