export type PeriodDirection = 'up' | 'down' | 'flat' | 'new'

export type PeriodMetric = {
  current: number
  previous: number
  change_pct: number | null
  direction: PeriodDirection
}

type StatCardProps = {
  label: string
  value: string | number
  hint: string
  tone?: 'blue' | 'green' | 'orange' | 'purple' | 'red'
  trend?: PeriodMetric
  trendLabel?: string
}

const toneClass = {
  blue: 'stat-card--blue',
  green: 'stat-card--green',
  orange: 'stat-card--orange',
  purple: 'stat-card--purple',
  red: 'stat-card--red',
}

function formatTrend(metric: PeriodMetric): string {
  if (metric.direction === 'new') return 'новые'
  if (metric.change_pct === null) return '—'
  if (metric.change_pct > 0) return `+${metric.change_pct}%`
  if (metric.change_pct < 0) return `${metric.change_pct}%`
  return '0%'
}

function trendArrow(direction: PeriodDirection): string {
  if (direction === 'up' || direction === 'new') return '↑'
  if (direction === 'down') return '↓'
  return '→'
}

export function StatCard({ label, value, hint, tone = 'blue', trend, trendLabel }: StatCardProps) {
  return (
    <article className={`stat-card ${toneClass[tone]}`}>
      <p className="stat-card__label">{label}</p>
      <p className="stat-card__value">{value}</p>
      {trend && (
        <p className={`stat-card__trend stat-card__trend--${trend.direction}`}>
          <span className="stat-card__trend-arrow" aria-hidden>
            {trendArrow(trend.direction)}
          </span>
          <span className="stat-card__trend-value">{formatTrend(trend)}</span>
          {trendLabel && <span className="stat-card__trend-label">{trendLabel}</span>}
        </p>
      )}
      <p className="stat-card__hint">{hint}</p>
    </article>
  )
}
