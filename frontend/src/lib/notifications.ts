import { useEffect, useSyncExternalStore } from 'react'
import { ApiError, bearer, request } from './api'
import { PHASE2_MOCK, mockDelay } from './analytics'
import { isExpiredSession } from './auth'
import type { AuthSession } from './auth'

/**
 * Phase 2 cleaner notifications with the location rule: a new task, a
 * reassignment or a proof result is only sent to cleaners of the complaint's
 * location. The backend owns that rule (M2); this screen trusts the feed it
 * is given and never filters someone else's location in by itself.
 *
 * Proposed contract (until M2 ships it, PHASE2_MOCK serves the same shapes):
 *   GET  /cleaner/notifications              → NotificationFeed
 *   POST /cleaner/notifications/{id}/read    → CleanerNotification
 *   POST /cleaner/notifications/read-all     → { updated: number }
 * A cleaner touching another location's notification gets 403.
 */

/** Matches analytics/records.py LOCATIONS, numbered for location_id. */
export const LOCATIONS = [
  { id: 1, name: 'Dadar' },
  { id: 2, name: 'Wadala' },
  { id: 3, name: 'Kalyan-Dombivali' },
] as const

export type NotificationKind =
  | 'task_assigned'
  | 'task_reassigned'
  | 'proof_rejected'
  | 'proof_verified'
  | 'area_report'

export interface CleanerNotification {
  id: string
  location_id: number
  location_name: string
  kind: NotificationKind
  title: string
  body: string
  task_id: string | null
  /** Photo-AI vocabulary, as in M3's records (wet, dry, sanitary, …). */
  waste_type: string | null
  /** domestic | moderate | dump_scale */
  severity: string | null
  created_at: string
  read_at: string | null
}

export interface NotificationFeed {
  /** The cleaner's own location; null for an admin, who sees every location. */
  location_id: number | null
  location_name: string | null
  notifications: CleanerNotification[]
}

/* ------------------------------------------------------------------ *
 * Mock backend — SYNTHETIC data, in memory, reset on page reload
 * ------------------------------------------------------------------ */

let mockRows: CleanerNotification[] | null = null
let mockSeq = 100

function minutesAgo(minutes: number) {
  return new Date(Date.now() - minutes * 60_000).toISOString()
}

function locationName(id: number) {
  return LOCATIONS.find((location) => location.id === id)?.name ?? `#${id}`
}

function mockNotification(
  locationId: number,
  kind: NotificationKind,
  minutes: number,
  extra: Partial<CleanerNotification>,
): CleanerNotification {
  mockSeq += 1
  return {
    id: `N-${mockSeq}`,
    location_id: locationId,
    location_name: locationName(locationId),
    kind,
    title: '',
    body: '',
    task_id: null,
    waste_type: null,
    severity: null,
    created_at: minutesAgo(minutes),
    read_at: null,
    ...extra,
  }
}

function seedMock(): CleanerNotification[] {
  const read = (minutes: number) => ({ read_at: minutesAgo(minutes) })
  return [
    mockNotification(1, 'task_assigned', 4, {
      title: 'New cleanup assigned',
      body: 'Overflowing bins behind Dadar station, platform 1 exit.',
      task_id: 'TSK-D-0142',
      waste_type: 'mixed',
      severity: 'moderate',
    }),
    mockNotification(1, 'proof_rejected', 38, {
      title: 'Proof photo rejected',
      body: 'The photo does not show the cleared spot. Retake it from the same angle as the report.',
      task_id: 'TSK-D-0131',
      waste_type: 'wet',
      severity: 'domestic',
    }),
    mockNotification(1, 'area_report', 95, {
      title: 'Dump-scale report in your area',
      body: 'Construction debris dumped near Kabutar Khana. An admin is reviewing it.',
      waste_type: 'hazardous',
      severity: 'dump_scale',
    }),
    mockNotification(1, 'proof_verified', 260, {
      title: 'Cleanup verified',
      body: 'Your proof for Ranade Road was accepted. The complaint is resolved.',
      task_id: 'TSK-D-0127',
      waste_type: 'dry',
      severity: 'domestic',
      ...read(200),
    }),
    mockNotification(1, 'task_reassigned', 1440, {
      title: 'Task reassigned to you',
      body: 'E-waste pickup on Gokhale Road moved to you from another cleaner.',
      task_id: 'TSK-D-0119',
      waste_type: 'e_waste',
      severity: 'domestic',
      ...read(1300),
    }),
    mockNotification(2, 'task_assigned', 12, {
      title: 'New cleanup assigned',
      body: 'Sanitary waste near Wadala bridge bus stop.',
      task_id: 'TSK-W-0088',
      waste_type: 'sanitary',
      severity: 'domestic',
    }),
    mockNotification(2, 'area_report', 70, {
      title: 'Repeated report in your area',
      body: 'Third report this week at Antop Hill market lane.',
      waste_type: 'mixed',
      severity: 'moderate',
    }),
    mockNotification(2, 'proof_verified', 600, {
      title: 'Cleanup verified',
      body: 'Your proof for Bhakti Park was accepted.',
      task_id: 'TSK-W-0081',
      waste_type: 'dry',
      severity: 'moderate',
      ...read(540),
    }),
    mockNotification(3, 'task_assigned', 25, {
      title: 'New cleanup assigned',
      body: 'Wet waste spilling onto the road outside Kalyan market.',
      task_id: 'TSK-K-0203',
      waste_type: 'wet',
      severity: 'moderate',
    }),
    mockNotification(3, 'proof_rejected', 180, {
      title: 'Proof photo rejected',
      body: 'Photo is too dark to verify. Upload one taken in daylight.',
      task_id: 'TSK-K-0197',
      waste_type: 'e_waste',
      severity: 'domestic',
    }),
    mockNotification(3, 'task_assigned', 2900, {
      title: 'New cleanup assigned',
      body: 'Garden waste heap at Dombivli East, MIDC road.',
      task_id: 'TSK-K-0170',
      waste_type: 'wet',
      severity: 'dump_scale',
      ...read(2800),
    }),
  ]
}

function rows() {
  mockRows ??= seedMock()
  return mockRows
}

/**
 * Stand-in for the server's "which location does this cleaner work in". The
 * real backend reads it from the user record; the mock derives it from the
 * account so every cleaner login lands somewhere stable, and lets the demo
 * preview another location.
 */
function mockLocationFor(session: AuthSession, previewId: number | null) {
  if (session.role === 'admin') return null
  if (previewId !== null) return previewId
  let hash = 0
  for (const char of session.subject)
    hash = (hash * 31 + char.charCodeAt(0)) | 0
  return LOCATIONS[Math.abs(hash) % LOCATIONS.length].id
}

function mockFeed(session: AuthSession, previewId: number | null) {
  const locationId = mockLocationFor(session, previewId)
  const notifications = rows()
    .filter((row) => locationId === null || row.location_id === locationId)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((row) => ({ ...row }))
  return {
    location_id: locationId,
    location_name: locationId === null ? null : locationName(locationId),
    notifications,
  } satisfies NotificationFeed
}

function mockMarkRead(
  session: AuthSession,
  previewId: number | null,
  id: string,
) {
  const row = rows().find((item) => item.id === id)
  if (!row) throw new ApiError(404, 'That notification no longer exists.')
  const own = mockLocationFor(session, previewId)
  if (own !== null && row.location_id !== own) {
    throw new ApiError(
      403,
      'This notification belongs to another location, so it is not yours to open.',
    )
  }
  row.read_at ??= new Date().toISOString()
  return { ...row }
}

/* ------------------------------------------------------------------ *
 * Client calls
 * ------------------------------------------------------------------ */

function fetchFeed(
  session: AuthSession,
  previewId: number | null,
  signal?: AbortSignal,
) {
  if (PHASE2_MOCK) return mockDelay(mockFeed(session, previewId))
  return request<NotificationFeed>('/cleaner/notifications', {
    headers: bearer(session.accessToken),
    signal,
  })
}

/* ------------------------------------------------------------------ *
 * Shared store: the layout's unread badge and the notifications page read
 * the same feed, so marking one read updates both without a second request.
 * ------------------------------------------------------------------ */

interface FeedState {
  feed: NotificationFeed | null
  loading: boolean
  error: string | null
  expired: boolean
  /** Mock-only: preview the feed as a cleaner of this location. */
  previewId: number | null
}

const INITIAL: FeedState = {
  feed: null,
  loading: false,
  error: null,
  expired: false,
  previewId: null,
}

let state: FeedState = INITIAL
let loadedFor: string | null = null
let controller: AbortController | null = null
const listeners = new Set<() => void>()

function set(patch: Partial<FeedState>) {
  state = { ...state, ...patch }
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

async function load(session: AuthSession) {
  controller?.abort()
  const current = new AbortController()
  controller = current
  set({ loading: true, error: null })
  try {
    const feed = await fetchFeed(session, state.previewId, current.signal)
    if (current.signal.aborted) return
    set({ feed, loading: false, expired: false })
  } catch (caught) {
    if (current.signal.aborted) return
    set({
      loading: false,
      expired: isExpiredSession(caught),
      error: caught instanceof Error ? caught.message : 'The request failed.',
    })
  }
}

/** Live mode re-checks for new notifications this often. */
const POLL_MS = 30_000

/** One poll timer however many components show the feed. */
let activeSession: AuthSession | null = null
let pollTimer: number | null = null
let users = 0

/**
 * The cleaner's notification feed. Loads once per signed-in account and keeps
 * polling in live mode; pass null while signed out.
 */
export function useNotificationFeed(session: AuthSession | null) {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => state,
    () => INITIAL,
  )
  const key = session ? `${session.subject}|${session.role}` : null

  useEffect(() => {
    activeSession = session
  })

  useEffect(() => {
    if (!key || !activeSession) {
      if (loadedFor !== null) {
        loadedFor = null
        controller?.abort()
        set({ ...INITIAL })
      }
      return
    }
    if (loadedFor !== key) {
      loadedFor = key
      set({ ...INITIAL })
      void load(activeSession)
    }
    users += 1
    if (!PHASE2_MOCK && pollTimer === null) {
      pollTimer = window.setInterval(() => {
        if (activeSession) void load(activeSession)
      }, POLL_MS)
    }
    return () => {
      users -= 1
      if (users === 0 && pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
    }
  }, [key])

  const unread =
    snapshot.feed?.notifications.filter((row) => !row.read_at).length ?? 0
  return { ...snapshot, unread }
}

export function reloadNotifications(session: AuthSession) {
  return load(session)
}

export function setPreviewLocation(session: AuthSession, id: number | null) {
  set({ previewId: id })
  return load(session)
}

/** Marks one read, optimistically; the server answer (or a 403) wins. */
export async function markNotificationRead(session: AuthSession, id: string) {
  const before = state.feed
  if (!before) return
  const stamp = new Date().toISOString()
  set({
    feed: {
      ...before,
      notifications: before.notifications.map((row) =>
        row.id === id ? { ...row, read_at: row.read_at ?? stamp } : row,
      ),
    },
  })
  try {
    const saved = PHASE2_MOCK
      ? await mockDelay(mockMarkRead(session, state.previewId, id), 120)
      : await request<CleanerNotification>(
          `/cleaner/notifications/${encodeURIComponent(id)}/read`,
          { method: 'POST', headers: bearer(session.accessToken) },
        )
    const latest = state.feed
    if (!latest) return
    set({
      feed: {
        ...latest,
        notifications: latest.notifications.map((row) =>
          row.id === id ? saved : row,
        ),
      },
    })
  } catch (caught) {
    set({ feed: before })
    throw caught
  }
}

export async function markAllNotificationsRead(session: AuthSession) {
  const unreadIds =
    state.feed?.notifications.filter((row) => !row.read_at).map((r) => r.id) ??
    []
  if (PHASE2_MOCK) {
    for (const id of unreadIds) mockMarkRead(session, state.previewId, id)
  } else {
    await request<{ updated: number }>('/cleaner/notifications/read-all', {
      method: 'POST',
      headers: bearer(session.accessToken),
    })
  }
  await load(session)
}

/**
 * Mock-only demo of the location rule: files a new report in `locationId` and
 * says whether the person viewing would be notified about it.
 */
export async function simulateIncomingReport(
  session: AuthSession,
  locationId: number,
) {
  const samples = [
    {
      waste_type: 'mixed',
      severity: 'moderate',
      body: 'Bags piled at a bus stop.',
    },
    {
      waste_type: 'wet',
      severity: 'domestic',
      body: 'Food waste outside a housing society gate.',
    },
    {
      waste_type: 'hazardous',
      severity: 'dump_scale',
      body: 'Paint drums dumped on an open plot.',
    },
  ]
  const sample = samples[mockSeq % samples.length]
  const row = mockNotification(locationId, 'task_assigned', 0, {
    title: 'New cleanup assigned',
    body: `${sample.body} (${locationName(locationId)})`,
    task_id: `TSK-SIM-${mockSeq}`,
    waste_type: sample.waste_type,
    severity: sample.severity,
  })
  rows().push(row)
  const own = mockLocationFor(session, state.previewId)
  await load(session)
  return { delivered: own === null || own === locationId, row }
}
