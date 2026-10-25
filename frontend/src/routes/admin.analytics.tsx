import { useMemo, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import {
  ChartTable,
  GroupedBarChart,
  LineChart,
  seriesColor,
} from '#/components/charts'
import type { Series } from '#/components/charts'
import {
  Callout,
  ErrorState,
  LoadingState,
  SectionCard,
  Skeleton,
} from '#/components/ui'
import {
  PHASE2_MOCK,
  basedOnLabel,
  getAnalyticsReport,
  getLocationComparison,
  isFallback,
  weekLabel,
} from '#/lib/analytics'
import type { AnalyticsReport, LocationComparison } from '#/lib/analytics'
import { signOut, useAuth } from '#/lib/auth'
import { getAuthToken, getAuthUser } from '#/lib/api'
import { aiSeverityLabel, aiWasteLabel } from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'
import { useApi } from '#/lib/use-api'
import type { ApiState } from '#/lib/use-api'

export const Route = createFileRoute('/admin/analytics')({
  component: AnalyticsPage,
})

/** Severity reads small → large, not alphabetically as M3 sorts it. */
const SEVERITY_ORDER = ['domestic', 'moderate', 'dump_scale']

function minutes(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : `${value} min`
}

function AnalyticsPage() {
  const { session } = useAuth()
  const token =
    (session?.role === 'admin' ? session.accessToken : null) ??
    (getAuthUser()?.role === 'admin' ? (getAuthToken() ?? undefined) : undefined)
  const comparison = useApi(
    token ? (signal) => getLocationComparison(token, signal) : null,
    [token],
  )
  const report = useApi(
    token ? (signal) => getAnalyticsReport(token, signal) : null,
    [token],
  )

  const data = comparison.data
  const [hidden, setHidden] = useState<string[]>([])
  const [groupBy, setGroupBy] = useState<'waste' | 'severity'>('waste')

  // Colour follows the location's place in the full list, so hiding one
  // never repaints the others.
  const allSeries: Series[] = useMemo(
    () =>
      (data?.locations ?? []).map((location, i) => ({
        key: location,
        label: location,
        slot: i + 1,
      })),
    [data],
  )
  const series = allSeries.filter((s) => !hidden.includes(s.key))

  function toggle(location: string) {
    setHidden((current) =>
      current.includes(location)
        ? current.filter((value) => value !== location)
        : // Keep at least one location on screen.
          current.length + 1 >= allSeries.length
          ? current
          : [...current, location],
    )
  }

  if (!token) {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to see location analytics.
      </Callout>
    )
  }

  return (
    <div className="grid gap-4">
      {comparison.error ? (
        <ErrorState
          title="Location analytics could not be loaded"
          message={comparison.error}
          onRetry={comparison.reload}
          onReauth={comparison.expired ? signOut : undefined}
        />
      ) : null}

      {data?.meta.synthetic_data || PHASE2_MOCK ? (
        <Callout tone="warn" title="Synthetic data">
          These figures come from simulated cleanups (M3’s sample output), not
          real ones. Use them to check the screens, not to draw conclusions.
        </Callout>
      ) : null}

      {/* One filter row above everything it scopes. */}
      <div className="filter-row">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-bold subtle">Locations</span>
          {allSeries.length === 0 ? (
            <Skeleton className="h-6 w-48" />
          ) : (
            allSeries.map((s) => {
              const on = !hidden.includes(s.key)
              return (
                <button
                  key={s.key}
                  type="button"
                  className="chip"
                  aria-pressed={on}
                  onClick={() => toggle(s.key)}
                >
                  <span
                    className="key-rect"
                    style={{ background: on ? seriesColor(s.slot) : undefined }}
                    aria-hidden="true"
                  />
                  {s.label}
                </button>
              )
            })
          )}
        </div>
        <div className="segmented" role="group" aria-label="Group cleanups by">
          {(
            [
              ['waste', 'Waste type'],
              ['severity', 'Severity'],
            ] as const
          ).map(([value, text]) => (
            <button
              key={value}
              type="button"
              aria-pressed={groupBy === value}
              onClick={() => setGroupBy(value)}
            >
              {text}
            </button>
          ))}
        </div>
      </div>

      {!data ? (
        comparison.error ? null : (
          <LoadingState label="Loading location analytics…" />
        )
      ) : (
        <>
          <Stats data={data} locations={series.map((s) => s.key)} />
          <ComparisonChart data={data} series={series} groupBy={groupBy} />
          <WeeklyChart data={data} series={series} />
          <LocationTable data={data} series={series} />
        </>
      )}

      <EstimatesCard
        report={report}
        locations={data ? series.map((s) => s.key) : null}
      />
    </div>
  )
}

function Stats({
  data,
  locations,
}: {
  data: LocationComparison
  locations: string[]
}) {
  const total = locations.reduce((sum, l) => sum + (data.totals[l] ?? 0), 0)
  const timed = locations.filter(
    (l) => typeof data.median_cleaning_minutes[l] === 'number',
  )
  const byClean = [...timed].sort(
    (a, b) =>
      (data.median_cleaning_minutes[a] ?? 0) -
      (data.median_cleaning_minutes[b] ?? 0),
  )
  const busiest = [...locations]
    .sort((a, b) => (data.totals[b] ?? 0) - (data.totals[a] ?? 0))
    .at(0)
  const fastest = byClean.at(0)
  const slowest = byClean.at(-1)

  const tiles = [
    {
      label: 'Cleanups',
      value: total.toLocaleString('en-IN'),
      note: `${data.weeks.length} weeks`,
    },
    {
      label: 'Busiest location',
      value: busiest
        ? (data.totals[busiest] ?? 0).toLocaleString('en-IN')
        : '—',
      note: busiest ?? '',
    },
    {
      label: 'Fastest median clean',
      value: fastest ? minutes(data.median_cleaning_minutes[fastest]) : '—',
      note: fastest ?? '',
    },
    {
      label: 'Slowest median clean',
      value: slowest ? minutes(data.median_cleaning_minutes[slowest]) : '—',
      note: slowest ?? '',
    },
  ]

  return (
    <section
      aria-label="Summary"
      className="grid grid-cols-2 gap-2 lg:grid-cols-4"
    >
      {tiles.map((tile) => (
        <div key={tile.label} className="stat">
          <p className="m-0 text-xs muted">{tile.label}</p>
          <p className="stat-value m-0 mt-1">{tile.value}</p>
          <p className="m-0 mt-0.5 truncate text-xs subtle">{tile.note}</p>
        </div>
      ))}
    </section>
  )
}

function ComparisonChart({
  data,
  series,
  groupBy,
}: {
  data: LocationComparison
  series: Series[]
  groupBy: 'waste' | 'severity'
}) {
  const source = groupBy === 'waste' ? data.by_waste_type : data.by_severity
  const keys =
    groupBy === 'waste'
      ? data.waste_types
      : SEVERITY_ORDER.filter((s) => data.severities.includes(s))
  const label = groupBy === 'waste' ? aiWasteLabel : aiSeverityLabel
  const categories = keys.map((key) => ({
    key,
    label: (label(key) ?? key).replace(/ waste$/, ''),
  }))
  const value = (location: string, key: string) => source[location]?.[key] ?? 0
  const title =
    groupBy === 'waste'
      ? 'Cleanups by waste type, per location'
      : 'Cleanups by severity, per location'

  return (
    <SectionCard title={title} meta="Count of cleanups">
      <GroupedBarChart
        label={title}
        categories={categories}
        series={series}
        value={value}
        unit="cleanups"
      />
      <ChartTable
        caption={title}
        columns={['Location', ...categories.map((c) => c.label)]}
        rows={series.map((s) => ({
          key: s.key,
          cells: [s.label, ...categories.map((c) => value(s.key, c.key))],
        }))}
      />
    </SectionCard>
  )
}

function WeeklyChart({
  data,
  series,
}: {
  data: LocationComparison
  series: Series[]
}) {
  const points = data.weeks.map((week) => ({
    key: week,
    label: weekLabel(week),
  }))
  const value = (location: string, week: string) =>
    data.weekly[location]?.[week] ?? 0
  const title = 'Cleanups per week'

  return (
    <SectionCard title={title} meta="ISO weeks · first and last may be partial">
      <LineChart
        label={title}
        points={points}
        series={series}
        value={value}
        unit="cleanups"
      />
      <ChartTable
        caption={title}
        columns={['Location', ...points.map((p) => p.label)]}
        rows={series.map((s) => ({
          key: s.key,
          cells: [s.label, ...points.map((p) => value(s.key, p.key))],
        }))}
      />
    </SectionCard>
  )
}

function LocationTable({
  data,
  series,
}: {
  data: LocationComparison
  series: Series[]
}) {
  const total = series.reduce((sum, s) => sum + (data.totals[s.key] ?? 0), 0)
  return (
    <SectionCard title="Location summary" bodyClassName="table-scroll">
      <table className="data-table numeric">
        <thead>
          <tr>
            <th scope="col">Location</th>
            <th scope="col">Cleanups</th>
            <th scope="col">Share</th>
            <th scope="col">Median cleaning</th>
            <th scope="col">Median response</th>
          </tr>
        </thead>
        <tbody>
          {series.map((s) => {
            const count = data.totals[s.key] ?? 0
            return (
              <tr key={s.key}>
                <th scope="row">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="key-rect"
                      style={{ background: seriesColor(s.slot) }}
                      aria-hidden="true"
                    />
                    {s.label}
                  </span>
                </th>
                <td>{count}</td>
                <td>{total ? `${Math.round((count / total) * 100)}%` : '—'}</td>
                <td>{minutes(data.median_cleaning_minutes[s.key])}</td>
                <td>{minutes(data.median_response_minutes[s.key])}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </SectionCard>
  )
}

function EstimatesCard({
  report,
  locations,
}: {
  report: ApiState<AnalyticsReport>
  locations: string[] | null
}) {
  const rows = useMemo(() => {
    const all = report.data?.cleanup_time_estimates ?? []
    return all
      .filter((row) => !locations || locations.includes(row.location))
      .sort(
        (a, b) =>
          a.location.localeCompare(b.location) ||
          SEVERITY_ORDER.indexOf(a.severity) -
            SEVERITY_ORDER.indexOf(b.severity),
      )
  }, [report.data, locations])

  return (
    <SectionCard
      title="Cleaning time estimates"
      meta={
        report.data
          ? `Generated ${formatDateTime(report.data.generated_at)}`
          : undefined
      }
      bodyClassName=""
    >
      <div className="card-pad pb-0">
        <p className="m-0 text-sm muted">
          Median cleaning time from past cleanups, using the most specific group
          that has at least 5 of them. Where a location has too few, the
          estimate falls back to a broader group, shown as{' '}
          <span className="pill" data-tone="warn">
            Fallback
          </span>
          . Not yet checked against real cleanups.
        </p>
      </div>
      {report.error ? (
        <div className="card-pad">
          <ErrorState
            title="Estimates could not be loaded"
            message={report.error}
            onRetry={report.reload}
          />
        </div>
      ) : !report.data ? (
        <div className="card-pad">
          <LoadingState label="Loading estimates…" />
        </div>
      ) : (
        <div className="table-scroll mt-3">
          <table className="data-table numeric">
            <thead>
              <tr>
                <th scope="col">Location</th>
                <th scope="col">Severity</th>
                <th scope="col">Estimate</th>
                <th scope="col">Based on</th>
                <th scope="col">Samples</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.location}-${row.severity}`}>
                  <th scope="row">{row.location}</th>
                  <td>{aiSeverityLabel(row.severity)}</td>
                  <td>
                    <strong>{minutes(row.estimated_minutes)}</strong>
                  </td>
                  <td>
                    <span className="inline-flex flex-wrap items-center gap-1.5">
                      {isFallback(row.based_on) ? (
                        <span className="pill" data-tone="warn">
                          Fallback
                        </span>
                      ) : (
                        <span className="pill" data-tone="ok">
                          Specific
                        </span>
                      )}
                      <span className="text-xs muted">
                        {basedOnLabel(row.based_on)}
                      </span>
                    </span>
                  </td>
                  <td>{row.training_samples}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  )
}
