/**
 * Timestamps are shown in IST (Asia/Kolkata). The backend sends them without a
 * zone, so STORED_ZONE says how to read them. Intl with a fixed timeZone and
 * locale renders identically on server and client.
 */
const IST = 'Asia/Kolkata'
// 'Z' if stored values are UTC, '+05:30' if they are IST
const STORED_ZONE = '+05:30'

function parseServerDate(value: string): Date | null {
  if (!value) return null
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(value)
  const iso = value.includes('T') ? value : value.replace(' ', 'T')
  const d = new Date(hasZone ? iso : iso + STORED_ZONE)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDate(iso: string) {
  const d = parseServerDate(iso)
  if (!d) return '-'
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: IST,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(d)
}

export function formatDateTime(iso: string) {
  const d = parseServerDate(iso)
  if (!d) return '-'
  const time = new Intl.DateTimeFormat('en-US', {
    timeZone: IST,
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(d)
  return `${formatDate(iso)}, ${time} IST`
}

/** Case age, used by the dashboard age filter (FR-17). */
export function ageInHours(iso: string, now: string) {
  const from = parseServerDate(iso)?.getTime()
  const to = parseServerDate(now)?.getTime()
  if (from == null || to == null) return 0
  return Math.max(0, (to - from) / 3_600_000)
}

export function formatAge(iso: string, now: string) {
  const mins = Math.round(ageInHours(iso, now) * 60)
  if (mins < 60) return `${mins} min`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} h ${mins % 60} min`
  return `${Math.floor(hours / 24)} d ${hours % 24} h`
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`
}