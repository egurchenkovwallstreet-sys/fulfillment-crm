import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("fulfillment")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Быстрый sync каждую минуту; полный — раз в 15 мин (архив 30 дн. для счётчика «В доставке»)
app.conf.beat_schedule = {
    "sync-wb-orders-quick": {
        "task": "apps.integrations.tasks.sync_wb_orders",
        "schedule": 60.0,
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
}
