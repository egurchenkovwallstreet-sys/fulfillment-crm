import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("fulfillment")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Синхронизация WB каждые ~1 мин (сборка FBS — актуальные «Новые»)
app.conf.beat_schedule = {
    "sync-wb-orders": {
        "task": "apps.integrations.tasks.sync_wb_orders",
        "schedule": 60.0,
    },
    "sync-wb-product-cards": {
        "task": "apps.integrations.tasks.sync_wb_product_cards",
        "schedule": crontab(hour=3, minute=0),
    },
}
