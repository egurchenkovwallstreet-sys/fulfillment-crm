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


def previous_week_bounds(day: date | None = None) -> tuple[date, date]:
  week_start, _ = calendar_week_bounds(day)
  prev_end = week_start - timedelta(days=1)
  prev_start = prev_end - timedelta(days=6)
  return prev_start, prev_end


def calendar_week_bounds_offset(weeks_ago: int = 0, day: date | None = None) -> tuple[date, date]:
  """Календарная неделя пн–вс, сдвинутая на weeks_ago назад (0 = текущая)."""
  week_start, week_end = calendar_week_bounds(day)
  if weeks_ago:
    shift = timedelta(weeks=weeks_ago)
    week_start -= shift
    week_end -= shift
  return week_start, week_end


def previous_month_bounds(day: date | None = None) -> tuple[date, date]:
  day = day or today_local()
  first_this_month = calendar_month_start(day)
  last_prev = first_this_month - timedelta(days=1)
  first_prev = last_prev.replace(day=1)
  return first_prev, last_prev


def days_back_to_cover_previous_month(day: date | None = None) -> int:
  day = day or today_local()
  prev_start, _ = previous_month_bounds(day)
  return (day - prev_start).days + 1
