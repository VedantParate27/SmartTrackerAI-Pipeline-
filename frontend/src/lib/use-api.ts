import { useCallback, useEffect, useRef, useState } from 'react'
import { isExpiredSession } from './auth'

export interface ApiState<T> {
  data: T | null
  error: string | null
  /** True when the failure was a 401, so the screen can offer a re-login. */
  expired: boolean
  loading: boolean
  reload: () => void
  setData: (value: T | null) => void
}

/**
 * One GET with loading, error, 401 and abort handling. Pass `null` as the
 * loader to skip the request (e.g. while signed out). Data survives a
 * `reload()` so the screen refreshes in place, but is cleared when `deps`
 * change so one record never flashes on another record's page.
 */
export function useApi<T>(
  load: ((signal: AbortSignal) => Promise<T>) | null,
  deps: ReadonlyArray<string | number | boolean | null | undefined>,
): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [loading, setLoading] = useState(false)
  const [nonce, setNonce] = useState(0)

  const loadRef = useRef(load)
  const depsKey = JSON.stringify(deps)
  const lastKey = useRef(depsKey)

  useEffect(() => {
    loadRef.current = load
  })

  useEffect(() => {
    if (lastKey.current !== depsKey) {
      lastKey.current = depsKey
      setData(null)
    }
    const run = loadRef.current
    if (!run) {
      setError(null)
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    run(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return
        setData(value)
        setExpired(false)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setExpired(isExpiredSession(caught))
        setError(
          caught instanceof Error ? caught.message : 'The request failed.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [depsKey, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, error, expired, loading, reload, setData }
}
