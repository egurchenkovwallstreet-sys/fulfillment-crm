"""Календарные периоды для аналитики — Europe/Moscow (см. TIME_ZONE в settings)."""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

WEEKDAY_LABELS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def today_local() -> date:
  return timezone.localdate()


def calendar_month_start(day: date | None = None) -> date:
  day = day or today_local()
  return day.replace(day=1)


def calendar_week_bounds(day: date | None = None) -> tuple[date, date]:
  """Календарная неделя пн–вс, как в отчётах WB."""
  day = day or today_local()
  week_start = day - timedelta(days=day.weekday())
  week_end = week_start + timedelta(days=6)
  return week_start, week_end


def days_since_month_start(day: date | None = None) -> int:
  day = day or today_local()
  return (day - calendar_month_start(day)).days + 1


def iter_week_days(week_start: date) -> list[tuple[date, str]]:
  return [
    (week_start + timedelta(days=offset), WEEKDAY_LABELS[offset])
    for offset in range(7)
  ]
