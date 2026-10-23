/**
 * SRS 7.3: timestamps are stored in UTC. They are formatted explicitly here
 * rather than with toLocaleString so the server and client render identically.
 */

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

function pad(value: number) {
  return String(value).padStart(2, '0')
}

/**
 * The backend writes timezone-aware UTC (models.utcnow), but SQLite drops the
 * offset, so timestamps come back as bare "2026-09-01T09:29:13.356485".
 * JavaScript reads an offsetless datetime as *local* time, which would shift
 * every rendered timestamp by the viewer's offset, so UTC is restored here.
 */
function parseBackendDate(iso: string) {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso.trim())
  return new Date(hasZone ? iso : `${iso.trim()}Z`)
}

export function formatDate(iso: string) {
  const date = parseBackendDate(iso)
  if (Number.isNaN(date.getTime())) return '-'
  return `${pad(date.getUTCDate())} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`
}

export function formatDateTime(iso: string) {
  const date = parseBackendDate(iso)
  if (Number.isNaN(date.getTime())) return '-'
  return `${formatDate(iso)}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
}

/** Case age, used by the dashboard age filter (FR-17). */
export function ageInHours(iso: string, now: string) {
  const from = parseBackendDate(iso).getTime()
  const to = parseBackendDate(now).getTime()
  if (Number.isNaN(from) || Number.isNaN(to)) return 0
  return Math.max(0, (to - from) / 3_600_000)
}

/** Seconds since a backend timestamp; 0 when it cannot be read. */
export function secondsSince(iso: string) {
  const time = parseBackendDate(iso).getTime()
  return Number.isNaN(time) ? 0 : (Date.now() - time) / 1000
}

export function formatAge(iso: string, now: string) {
  const hours = ageInHours(iso, now)
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${Math.round(hours)} h`
  return `${Math.round(hours / 24)} d`
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`
}
