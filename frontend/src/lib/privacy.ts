import { useEffect, useState } from 'react'
import { api } from '../api/client.ts'
import type { PrivacyInfo } from '../api/types.ts'

// The settings don't change while the app is open: fetch once and share.
let cached: Promise<PrivacyInfo> | null = null

/** How this deployment handles uploaded plans (PRD 4.14). Null while loading or if unavailable. */
export function usePrivacyInfo(): PrivacyInfo | null {
  const [info, setInfo] = useState<PrivacyInfo | null>(null)
  useEffect(() => {
    let cancelled = false
    cached ??= api.public.privacy().catch((err) => {
      cached = null // try again next time
      throw err
    })
    cached.then((i) => !cancelled && setInfo(i)).catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])
  return info
}
