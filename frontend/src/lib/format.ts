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

export function formatDate(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '-'
  return `${pad(date.getUTCDate())} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`
}

export function formatDateTime(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '-'
  return `${formatDate(iso)}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
}

/** Case age, used by the dashboard age filter (FR-17). */
export function ageInHours(iso: string, now: string) {
  const from = new Date(iso).getTime()
  const to = new Date(now).getTime()
  if (Number.isNaN(from) || Number.isNaN(to)) return 0
  return Math.max(0, (to - from) / 3_600_000)
}

export function formatAge(iso: string, now: string) {
  const hours = ageInHours(iso, now)
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${Math.round(hours)} h`
  return `${Math.round(hours / 24)} d`
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`
}
