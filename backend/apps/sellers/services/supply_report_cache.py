"""Снимки месячного отчёта по поставкам — обновление раз в сутки."""
from __future__ import annotations

import logging

from datetime import date

from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.sellers.services.supply_report import (
  load_supply_report,
  months_to_refresh,
  prune_supply_report_snapshots,
)

logger = logging.getLogger(__name__)


def get_supply_report_snapshot(
  fulfillment: Fulfillment,
  *,
  month: date,
) -> dict | None:
  from apps.sellers.models import SupplyReportSnapshot

  row = SupplyReportSnapshot.objects.filter(
    fulfillment=fulfillment,
    month=month.replace(day=1),
  ).first()
  if not row:
    return None
  payload = row.payload
  if not isinstance(payload, dict):
    return None
  payload = dict(payload)
  payload["cached_at"] = row.built_at.isoformat()
  payload["source"] = "snapshot"
  return payload


def rebuild_supply_report_snapshot(
  fulfillment: Fulfillment,
  *,
  month: date,
) -> dict:
  from apps.sellers.models import SupplyReportSnapshot

  month = month.replace(day=1)
  payload = load_supply_report(fulfillment, month=month)
  SupplyReportSnapshot.objects.update_or_create(
    fulfillment=fulfillment,
    month=month,
    defaults={"payload": payload, "built_at": timezone.now()},
  )
  logger.info(
    "Supply report snapshot rebuilt: fulfillment=%s month=%s supplies=%s",
    fulfillment.id,
    month.isoformat(),
    payload["totals"]["supplies"],
  )
  return payload


def rebuild_supply_report_snapshots_for_fulfillment(fulfillment: Fulfillment) -> list[dict]:
  results = []
  for month in months_to_refresh():
    results.append(rebuild_supply_report_snapshot(fulfillment, month=month))
  return results


def rebuild_all_supply_report_snapshots() -> dict:
  results = []
  for fulfillment in Fulfillment.objects.all().order_by("id"):
    stats = rebuild_supply_report_snapshots_for_fulfillment(fulfillment)
    results.append(
      {
        "fulfillment_id": fulfillment.id,
        "months": [row["month"] for row in stats],
        "supplies": sum(row["totals"]["supplies"] for row in stats),
      }
    )
  deleted = prune_supply_report_snapshots()
  return {"fulfillments": len(results), "results": results, "deleted_snapshots": deleted}
