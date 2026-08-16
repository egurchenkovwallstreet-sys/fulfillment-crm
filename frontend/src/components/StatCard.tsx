type StatCardProps = {
  label: string
  value: string | number
  hint: string
  tone?: 'blue' | 'green' | 'orange' | 'purple'
}

const toneClass = {
  blue: 'stat-card--blue',
  green: 'stat-card--green',
  orange: 'stat-card--orange',
  purple: 'stat-card--purple',
}

export function StatCard({ label, value, hint, tone = 'blue' }: StatCardProps) {
  return (
    <article className={`stat-card ${toneClass[tone]}`}>
      <p className="stat-card__label">{label}</p>
      <p className="stat-card__value">{value}</p>
      <p className="stat-card__hint">{hint}</p>
    </article>
  )
}
