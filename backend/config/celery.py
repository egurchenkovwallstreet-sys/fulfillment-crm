import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("fulfillment")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Быстрый sync каждые 2 мин (новые заказы WB); полный — раз в 15 мин
app.conf.beat_schedule = {
    "sync-wb-delivery-scans": {
        "task": "apps.integrations.tasks.sync_wb_delivery_scans",
        "schedule": 120.0,
    },
    "sync-wb-orders-quick": {
        "task": "apps.integrations.tasks.sync_wb_orders",
        "schedule": 120.0,
        "kwargs": {"quick": True},
    },
    "sync-wb-orders-full": {
        "task": "apps.integrations.tasks.sync_wb_orders",
        "schedule": crontab(minute="*/15"),
        "kwargs": {"quick": False},
    },
    "sync-wb-product-cards": {
        "task": "apps.integrations.tasks.sync_wb_product_cards",
        "schedule": crontab(hour=3, minute=0),
    },
    "sync-wb-barcode-aliases": {
        "task": "apps.integrations.tasks.sync_wb_barcode_aliases",
        "schedule": crontab(hour=3, minute=15),  # раз в сутки ~03:15 МСК (окно 02–05)
    },
    "sync-ozon-orders": {
        "task": "apps.integrations.tasks.sync_ozon_orders",
        "schedule": 60.0,
    },
    "verify-pending-marking": {
        "task": "apps.integrations.tasks.verify_pending_marking_codes",
        "schedule": 5.0,
    },
    "scan-off-crm-shipments": {
        "task": "apps.integrations.tasks.scan_off_crm_shipments",
        "schedule": crontab(hour=4, minute=0),
    },
    "rebuild-supply-report-snapshots": {
        "task": "apps.integrations.tasks.rebuild_supply_report_snapshots",
        "schedule": crontab(hour=4, minute=30),
    },
    "reconcile-stuck-delivery": {
        "task": "apps.integrations.tasks.reconcile_stuck_delivery_orders",
        "schedule": crontab(hour=4, minute=0),
    },
    "clear-daily-marking-codes": {
        "task": "apps.integrations.tasks.clear_daily_marking_codes",
        "schedule": crontab(hour=23, minute=59),
    },
    "accrue-daily-liter-storage": {
        "task": "apps.integrations.tasks.accrue_daily_storage_charges",
        "schedule": crontab(hour=0, minute=5),
    },
    "refresh-admin-billing-cache": {
        "task": "apps.integrations.tasks.refresh_all_admin_billing_caches",
        "schedule": 7200.0,
    },
}
