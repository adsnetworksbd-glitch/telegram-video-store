import { useEffect, useMemo, useState } from 'react'
import { videosApi, packagesApi } from '@/api'
import type { Video, Package } from '@/types'

// Entitlements and orders only carry a content id. The Backend schema has
// optional joined `video` / `package` fields on entitlements (not filled yet),
// so: use the joined data when present, otherwise resolve once per id and cache.

export interface ContentInfo {
  type: 'video' | 'package'
  id: string
  title: string
  thumbnail_url: string
  subtitle: string
}

interface Ref {
  content_type: 'video' | 'package'
  content_id: string
  video?: Video | null
  package?: Package | null
}

const cache = new Map<string, Promise<ContentInfo | null>>()
const key = (t: string, id: string) => `${t}:${id}`

export function fromVideo(v: Video): ContentInfo {
  return { type: 'video', id: v.id, title: v.title, thumbnail_url: v.thumbnail_url, subtitle: v.quality }
}
export function fromPackage(p: Package): ContentInfo {
  return { type: 'package', id: p.id, title: p.name, thumbnail_url: p.thumbnail_url, subtitle: `${p.video_count}টি ভিডিও` }
}

function lookup(type: 'video' | 'package', id: string): Promise<ContentInfo | null> {
  const k = key(type, id)
  let p = cache.get(k)
  if (!p) {
    p = (type === 'video' ? videosApi.detail(id) : packagesApi.detail(id))
      .then((r) => (type === 'video' ? fromVideo(r.data as Video) : fromPackage(r.data as Package)))
      .catch(() => { cache.delete(k); return null })   // allow a later retry
    cache.set(k, p)
  }
  return p
}

export function useContentLookup(refs: Ref[]): (type: 'video' | 'package', id: string) => ContentInfo | undefined {
  const [resolved, setResolved] = useState<Record<string, ContentInfo>>({})

  const joined = useMemo(() => {
    const m: Record<string, ContentInfo> = {}
    for (const r of refs) {
      if (r.content_type === 'video' && r.video) m[key('video', r.content_id)] = fromVideo(r.video)
      if (r.content_type === 'package' && r.package) m[key('package', r.content_id)] = fromPackage(r.package)
    }
    return m
  }, [refs])

  const needed = useMemo(() => {
    const seen = new Set<string>()
    const out: Array<['video' | 'package', string]> = []
    for (const r of refs) {
      const k = key(r.content_type, r.content_id)
      if (joined[k] || seen.has(k)) continue
      seen.add(k)
      out.push([r.content_type, r.content_id])
    }
    return out
  }, [refs, joined])

  const neededKey = needed.map(([t, id]) => key(t, id)).join('|')

  useEffect(() => {
    let alive = true
    for (const [t, id] of needed) {
      void lookup(t, id).then((info) => {
        if (alive && info) setResolved((prev) => (prev[key(t, id)] ? prev : { ...prev, [key(t, id)]: info }))
      })
    }
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neededKey])

  return (type, id) => joined[key(type, id)] ?? resolved[key(type, id)]
}
