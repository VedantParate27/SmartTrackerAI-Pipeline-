import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react'

/**
 * Small dependency-free SVG charts for the Phase 2 analytics screen.
 *
 * Colour: every series carries a fixed categorical slot (`--series-N` in
 * styles.css, validated for colour-blind separation in light and dark), chosen
 * by the entity — never by its rank — so filtering never repaints survivors.
 * Text always uses text tokens; identity comes from the swatch beside it.
 */

export interface Series {
  key: string
  label: string
  /** 1-based categorical slot. */
  slot: number
}

export interface Category {
  key: string
  label: string
}

export const seriesColor = (slot: number) =>
  `var(--series-${((slot - 1) % 8) + 1})`

/** Width of an element, tracked so the SVG draws at real pixels (crisp text). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    setWidth(node.clientWidth)
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.floor(entry.contentRect.width)),
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

/** About four round ticks from 0 to just above `max`. */
function niceTicks(max: number) {
  if (max <= 0) return [0, 1]
  const rough = max / 4
  const power = 10 ** Math.floor(Math.log10(rough))
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ??
    10 * power
  const ticks: number[] = []
  for (let value = 0; value < max + step; value += step) ticks.push(value)
  return ticks
}

function compact(value: number) {
  return value >= 1000 ? `${Math.round(value / 100) / 10}K` : String(value)
}

/** A column with a 4px rounded data end, square on the baseline. */
function columnPath(x: number, y: number, w: number, h: number) {
  if (h <= 0) return ''
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

interface TooltipRow {
  key: string
  label: string
  slot: number
  value: string
}

function Tooltip({
  x,
  width,
  title,
  rows,
  line,
}: {
  x: number
  width: number
  title: string
  rows: TooltipRow[]
  line?: boolean
}) {
  // Flip to the left of the pointer near the right edge.
  const flip = x > width - 190
  return (
    <div
      className="chart-tip"
      style={{
        left: flip ? undefined : x + 12,
        right: flip ? width - x + 12 : undefined,
      }}
      role="status"
    >
      <p className="chart-tip-title">{title}</p>
      {rows.map((row) => (
        <p key={row.key} className="chart-tip-row">
          <span
            className={line ? 'key-line' : 'key-line key-line-thick'}
            style={{ background: seriesColor(row.slot) }}
            aria-hidden="true"
          />
          <strong>{row.value}</strong>
          <span className="subtle">{row.label}</span>
        </p>
      ))}
    </div>
  )
}

export function Legend({
  series,
  shape,
}: {
  series: Series[]
  shape: 'rect' | 'line'
}) {
  if (series.length < 2) return null
  return (
    <ul className="chart-legend" aria-label="Legend">
      {series.map((item) => (
        <li key={item.key}>
          <span
            className={shape === 'line' ? 'key-line' : 'key-rect'}
            style={{ background: seriesColor(item.slot) }}
            aria-hidden="true"
          />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

const PLOT_H = 240
const AXIS_H = 30
const PAD_TOP = 14
const PAD_LEFT = 40
const PAD_RIGHT = 12

/* ------------------------------------------------------------------ *
 * Grouped columns
 * ------------------------------------------------------------------ */

export function GroupedBarChart({
  label,
  categories,
  series,
  value,
  unit,
}: {
  /** Accessible name for the figure. */
  label: string
  categories: Category[]
  series: Series[]
  value: (seriesKey: string, categoryKey: string) => number
  unit: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)

  const max = Math.max(
    0,
    ...categories.flatMap((c) => series.map((s) => value(s.key, c.key))),
  )
  const ticks = niceTicks(max)
  const top = ticks.at(-1) ?? 1
  const plotW = Math.max(0, width - PAD_LEFT - PAD_RIGHT)
  const band = categories.length ? plotW / categories.length : 0
  const gap = 2
  const barW = Math.max(
    4,
    Math.min(24, (band * 0.72 - gap * (series.length - 1)) / series.length),
  )
  const groupW = barW * series.length + gap * (series.length - 1)
  const y = (v: number) => PAD_TOP + PLOT_H - (v / top) * PLOT_H
  // Narrow bands (phones) stagger category labels onto two rows.
  const stagger = band < 64
  const axisH = AXIS_H + (stagger ? 14 : 0)

  return (
    <figure className="chart" aria-label={label}>
      <div ref={ref} className="chart-frame">
        {width > 0 ? (
          <svg
            width={width}
            height={PAD_TOP + PLOT_H + axisH}
            role="img"
            aria-label={`${label}. The table below lists every value.`}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  className="chart-grid"
                  x1={PAD_LEFT}
                  x2={width - PAD_RIGHT}
                  y1={y(tick)}
                  y2={y(tick)}
                />
                <text
                  className="chart-tick"
                  x={PAD_LEFT - 8}
                  y={y(tick)}
                  dy="0.32em"
                  textAnchor="end"
                >
                  {compact(tick)}
                </text>
              </g>
            ))}
            {categories.map((category, ci) => {
              const x0 = PAD_LEFT + band * ci + (band - groupW) / 2
              return (
                <g
                  key={category.key}
                  className="chart-group"
                  data-dim={active !== null && active !== ci ? '' : undefined}
                >
                  {series.map((s, si) => {
                    const v = value(s.key, category.key)
                    const x = x0 + si * (barW + gap)
                    return (
                      <path
                        key={s.key}
                        d={columnPath(x, y(v), barW, y(0) - y(v))}
                        fill={seriesColor(s.slot)}
                      />
                    )
                  })}
                  <text
                    className="chart-tick"
                    x={PAD_LEFT + band * ci + band / 2}
                    y={PAD_TOP + PLOT_H + 18 + (stagger && ci % 2 ? 14 : 0)}
                    textAnchor="middle"
                  >
                    {category.label}
                  </text>
                  {/* The hit target is the whole band, not the painted pixels. */}
                  <rect
                    className="chart-hit"
                    x={PAD_LEFT + band * ci}
                    y={PAD_TOP}
                    width={band}
                    height={PLOT_H + axisH}
                    tabIndex={0}
                    aria-label={`${category.label}: ${series
                      .map((s) => `${s.label} ${value(s.key, category.key)}`)
                      .join(', ')}`}
                    onPointerEnter={() => setActive(ci)}
                    onPointerLeave={() => setActive(null)}
                    onFocus={() => setActive(ci)}
                    onBlur={() => setActive(null)}
                  />
                </g>
              )
            })}
            <line
              className="chart-axis"
              x1={PAD_LEFT}
              x2={width - PAD_RIGHT}
              y1={y(0)}
              y2={y(0)}
            />
          </svg>
        ) : (
          <div style={{ height: PAD_TOP + PLOT_H + axisH }} />
        )}
        {active !== null && categories[active] ? (
          <Tooltip
            x={PAD_LEFT + band * active + band / 2 + groupW / 2}
            width={width}
            title={categories[active].label}
            rows={series.map((s) => ({
              key: s.key,
              label: s.label,
              slot: s.slot,
              value: `${value(s.key, categories[active].key)} ${unit}`,
            }))}
          />
        ) : null}
      </div>
      <Legend series={series} shape="rect" />
    </figure>
  )
}

/* ------------------------------------------------------------------ *
 * Lines over time, with a crosshair that snaps to the nearest point
 * ------------------------------------------------------------------ */

export function LineChart({
  label,
  points,
  series,
  value,
  unit,
}: {
  label: string
  /** X positions in order (e.g. weeks). */
  points: Category[]
  series: Series[]
  value: (seriesKey: string, pointKey: string) => number
  unit: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)

  const max = Math.max(
    0,
    ...points.flatMap((p) => series.map((s) => value(s.key, p.key))),
  )
  const ticks = niceTicks(max)
  const top = ticks.at(-1) ?? 1
  const y = (v: number) => PAD_TOP + PLOT_H - (v / top) * PLOT_H

  // Direct end labels only when they do not collide; else the legend carries it.
  const last = points.length - 1
  const ends = series
    .map((s) => ({ s, y: y(value(s.key, points[last]?.key ?? '')) }))
    .sort((a, b) => a.y - b.y)
  const endLabels =
    series.length <= 4 &&
    last >= 0 &&
    ends.every((end, i) => i === 0 || end.y - ends[i - 1].y >= 14)
  // Room on the right only when end labels are actually drawn.
  const padRight = endLabels ? 112 : PAD_RIGHT + 8
  const plotW = Math.max(0, width - PAD_LEFT - padRight)
  const step = points.length > 1 ? plotW / (points.length - 1) : 0
  const x = (i: number) => PAD_LEFT + (points.length > 1 ? i * step : plotW / 2)

  function snap(event: PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - box.left
    // The hit rect starts half a step before the first point.
    const i = step ? Math.floor(px / step) : 0
    setActive(Math.max(0, Math.min(last, i)))
  }

  function keys(event: KeyboardEvent<SVGRectElement>) {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const delta = event.key === 'ArrowRight' ? 1 : -1
      setActive((current) =>
        Math.max(
          0,
          Math.min(last, (current ?? (delta > 0 ? -1 : last + 1)) + delta),
        ),
      )
    }
  }

  return (
    <figure className="chart" aria-label={label}>
      <div ref={ref} className="chart-frame">
        {width > 0 ? (
          <svg
            width={width}
            height={PAD_TOP + PLOT_H + AXIS_H}
            role="img"
            aria-label={`${label}. The table below lists every value.`}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  className="chart-grid"
                  x1={PAD_LEFT}
                  x2={width - padRight}
                  y1={y(tick)}
                  y2={y(tick)}
                />
                <text
                  className="chart-tick"
                  x={PAD_LEFT - 8}
                  y={y(tick)}
                  dy="0.32em"
                  textAnchor="end"
                >
                  {compact(tick)}
                </text>
              </g>
            ))}
            {points.map((point, i) => (
              <text
                key={point.key}
                className="chart-tick"
                x={x(i)}
                y={PAD_TOP + PLOT_H + 18}
                textAnchor="middle"
              >
                {point.label}
              </text>
            ))}
            <line
              className="chart-axis"
              x1={PAD_LEFT}
              x2={width - padRight}
              y1={y(0)}
              y2={y(0)}
            />
            {active !== null ? (
              <line
                className="chart-crosshair"
                x1={x(active)}
                x2={x(active)}
                y1={PAD_TOP}
                y2={PAD_TOP + PLOT_H}
              />
            ) : null}
            {series.map((s) => (
              <g key={s.key}>
                <polyline
                  className="chart-line"
                  points={points
                    .map((p, i) => `${x(i)},${y(value(s.key, p.key))}`)
                    .join(' ')}
                  stroke={seriesColor(s.slot)}
                />
                {last >= 0 ? (
                  <circle
                    className="chart-dot"
                    cx={x(active ?? last)}
                    cy={y(value(s.key, points[active ?? last].key))}
                    r={4}
                    fill={seriesColor(s.slot)}
                  />
                ) : null}
              </g>
            ))}
            {endLabels
              ? series.map((s) => (
                  <text
                    key={s.key}
                    className="chart-end-label"
                    x={x(last) + 10}
                    y={y(value(s.key, points[last].key))}
                    dy="0.32em"
                  >
                    {s.label}
                  </text>
                ))
              : null}
            <rect
              className="chart-hit"
              x={PAD_LEFT - step / 2}
              y={PAD_TOP}
              width={plotW + step}
              height={PLOT_H}
              tabIndex={0}
              aria-label={`${label}. Use the left and right arrow keys to read each point.`}
              onPointerMove={snap}
              onPointerLeave={() => setActive(null)}
              onKeyDown={keys}
              onFocus={() => setActive((current) => current ?? last)}
              onBlur={() => setActive(null)}
            />
          </svg>
        ) : (
          <div style={{ height: PAD_TOP + PLOT_H + AXIS_H }} />
        )}
        {active !== null && points[active] ? (
          <Tooltip
            line
            x={x(active)}
            width={width}
            title={points[active].label}
            rows={series.map((s) => ({
              key: s.key,
              label: s.label,
              slot: s.slot,
              value: `${value(s.key, points[active].key)} ${unit}`,
            }))}
          />
        ) : null}
      </div>
      <Legend series={series} shape="line" />
    </figure>
  )
}

/** The table-view twin every chart ships with. */
export function ChartTable({
  caption,
  columns,
  rows,
}: {
  caption: string
  columns: string[]
  rows: Array<{ key: string; cells: ReactNode[] }>
}) {
  return (
    <details className="chart-table">
      <summary>Show as table</summary>
      <div className="table-scroll mt-2">
        <table className="data-table numeric">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                {row.cells.map((cell, i) =>
                  i === 0 ? (
                    <th key={i} scope="row">
                      {cell}
                    </th>
                  ) : (
                    <td key={i}>{cell}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
