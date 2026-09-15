from django.urls import path

from .views import CeleryTaskStatusView

urlpatterns = [
  path("tasks/<str:task_id>/", CeleryTaskStatusView.as_view(), name="celery_task_status"),
]
