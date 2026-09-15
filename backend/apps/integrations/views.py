"""API для фоновых задач Celery."""
from celery.result import AsyncResult
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class CeleryTaskStatusView(APIView):
  permission_classes = [IsAuthenticated]

  def get(self, request, task_id):
    result = AsyncResult(task_id)
    payload = {
      "task_id": task_id,
      "state": result.state,
      "ready": result.ready(),
    }
    if result.ready():
      if result.successful():
        payload["result"] = result.result
      else:
        payload["error"] = str(result.result)
    return Response(payload)
