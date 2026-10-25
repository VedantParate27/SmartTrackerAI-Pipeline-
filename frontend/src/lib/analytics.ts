import { bearer, request } from './api'
import comparisonSample from './mock/location-comparison.json'
import reportSample from './mock/analytics-report.json'

/**
 * Phase 2 location analytics. The shapes mirror M3's analytics module exactly
 * (analytics/comparison.py → compare_locations, analytics/report.py), so the
 * live endpoint can return that output unchanged.
 *
 * Until M2/M3 expose the endpoints, the screens read M3's own sample output,
 * which is SYNTHETIC. Set VITE_PHASE2_MOCK=false to call the backend instead.
 */
export const PHASE2_MOCK = import.meta.env.VITE_PHASE2_MOCK === 'true'

/** Keyed by location name; a live endpoint may omit a key, so reads guard. */
type ByLocation<T> = Record<string, T | undefined>
type Counts = Record<string, number | undefined>

/** compare_locations() output. */
export interface LocationComparison {
  meta: { records: number; sources: string[]; synthetic_data: boolean }
  locations: string[]
  waste_types: string[]
  severities: string[]
  /** ISO weeks, e.g. "2026-W41". */
  weeks: string[]
  cleaners: string[]
  totals: ByLocation<number>
  by_waste_type: ByLocation<Counts>
  by_severity: ByLocation<Counts>
  weekly: ByLocation<Counts>
  median_cleaning_minutes: ByLocation<number | null>
  median_response_minutes: ByLocation<number | null>
  cleaner_totals: Record<string, number>
  cleaner_median_cleaning_minutes: Record<string, number | null>
  cleaner_by_location: Record<
    string,
    ByLocation<{ count: number; median_cleaning_minutes: number | null }>
  >
}

/** One row of report.py's cleanup_time_estimates. */
export interface TimeEstimate {
  location: string
  severity: string
  records: number
  estimated_minutes: number | null
  /** The most specific group with enough samples, e.g. "location+severity". */
  based_on: string
  training_samples: number
}

export interface AnalyticsReport {
  generated_at: string
  data_type: string
  total_records: number
  cleanup_time_estimates: TimeEstimate[]
}

/** Proposed: GET /admin/analytics/locations (all locations; the screen filters). */
export function getLocationComparison(
  accessToken: string,
  signal?: AbortSignal,
  locations?: string[],
): Promise<LocationComparison> {
  if (PHASE2_MOCK) return mockDelay(comparisonSample as LocationComparison)
  const qs = locations && locations.length > 0 ? `?locations=${encodeURIComponent(locations.join(','))}` : ''
  return request<LocationComparison>(`/admin/analytics/locations${qs}`, {
    headers: bearer(accessToken),
    signal,
  })
}

/** Proposed: GET /admin/analytics/time-estimates */
export function getAnalyticsReport(
  accessToken: string,
  signal?: AbortSignal,
): Promise<AnalyticsReport> {
  if (PHASE2_MOCK) return mockDelay(reportSample as AnalyticsReport)
  return request<AnalyticsReport>('/admin/analytics/time-estimates', {
    headers: bearer(accessToken),
    signal,
  })
}

/** A short wait so the loading state is exercised the same way as live data. */
export function mockDelay<T>(value: T, ms = 350): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms))
}

/** "2026-W41" → "Wk 41". */
export function weekLabel(week: string) {
  const match = /W(\d+)$/.exec(week)
  return match ? `Wk ${Number(match[1])}` : week
}

/** "location+waste_type+severity" → "Location, waste type and severity". */
export function basedOnLabel(basedOn: string) {
  if (basedOn === 'overall') return 'Overall median'
  const parts = basedOn.split('+').map((part) => part.replaceAll('_', ' '))
  const text =
    parts.length > 1
      ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`
      : parts[0]
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The estimator's most specific level; anything broader is a fallback. */
export function isFallback(basedOn: string) {
  return basedOn !== 'location+waste_type+severity'
}
