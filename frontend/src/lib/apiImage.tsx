import { useEffect, useState, type ImgHTMLAttributes } from 'react'
import { isGuestMode } from '../api/client.ts'

const THUMB = /^\/api\/projects\/([0-9a-f]{24})\/files\/([0-9a-f]{24})\/pages\/(\d+)\/thumbnail$/
const cache = new Map<string, Promise<string | null>>()

/** For guests, an API image URL becomes an object URL: page thumbnails come straight from the
 * browser's store; anything else (plan previews) is rendered through the guest dispatcher. */
async function resolve(src: string): Promise<string | null> {
  const thumb = THUMB.exec(src)
  if (thumb) {
    const [, projectId, fileId, page] = thumb
    const { localStore } = await import('./localStore.ts')
    const { localFileUrl } = await import('../api/guest.ts')
    const project = await localStore.getProject(projectId)
    const bp = project?.blueprints.find((b) => (b._id as { $oid: string }).$oid === fileId)
    const pages = (bp?.pages as { index: number; thumbnail_id?: { $oid: string } }[] | undefined) ?? []
    const id = pages.find((p) => p.index === Number(page))?.thumbnail_id?.$oid
    return id ? localFileUrl(id) : null
  }
  const { guestCall } = await import('../api/guest.ts')
  const result = await guestCall('GET', src.replace(/^\/api/, ''))
  return result.blob ? URL.createObjectURL(result.blob) : null
}

export function useApiImage(src: string): string | null {
  const guest = isGuestMode()
  const [resolved, setResolved] = useState<{ src: string; url: string | null } | null>(null)
  useEffect(() => {
    if (!guest || !src) return
    let cancelled = false
    if (!cache.has(src)) cache.set(src, resolve(src).catch(() => null))
    void cache.get(src)!.then((url) => !cancelled && setResolved({ src, url }))
    return () => {
      cancelled = true
    }
  }, [src, guest])
  if (!guest) return src || null // signed in: the API URL works as it is
  return resolved?.src === src ? resolved.url : null
}

/** <img> that also works for projects kept in the browser. */
export function ApiImage({ src, ...props }: ImgHTMLAttributes<HTMLImageElement> & { src: string }) {
  const url = useApiImage(src)
  if (!url) return <span className={`inline-block animate-pulse bg-slate-100 ${props.className ?? ''}`} aria-hidden="true" />
  return <img src={url} {...props} />
}
