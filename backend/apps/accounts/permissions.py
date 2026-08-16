from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
  def has_permission(self, request, view):
    return (
      request.user
      and request.user.is_authenticated
      and request.user.role == "admin"
    )


class IsManager(BasePermission):
  def has_permission(self, request, view):
    return (
      request.user
      and request.user.is_authenticated
      and request.user.role in ("admin", "manager")
    )


class IsSeller(BasePermission):
  def has_permission(self, request, view):
    return (
      request.user
      and request.user.is_authenticated
      and request.user.role == "seller"
    )


class NoFinancialData(BasePermission):
  """Менеджер не видит финансовые данные (TZ п. 3.2)."""

  def has_permission(self, request, view):
    if not request.user or not request.user.is_authenticated:
      return False
    return request.user.role != "manager"
