from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class Fulfillment(models.Model):
  """Оператор фулфилмента (tenant). Каждый экземпляр изолирован."""

  name = models.CharField("Название", max_length=255)
  slug = models.SlugField("Код", max_length=100, unique=True)
  is_active = models.BooleanField("Активен", default=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Фулфилмент"
    verbose_name_plural = "Фулфилменты"
    ordering = ["name"]

  def __str__(self):
    return self.name


class User(AbstractUser):
  class Role(models.TextChoices):
    ADMIN = "admin", "Администратор"
    MANAGER = "manager", "Менеджер"
    SELLER = "seller", "Селлер"

  objects = UserManager()

  role = models.CharField(
    max_length=20,
    choices=Role.choices,
    default=Role.MANAGER,
  )
  fulfillment = models.ForeignKey(
    Fulfillment,
    on_delete=models.CASCADE,
    null=True,
    blank=True,
    related_name="users",
    verbose_name="Фулфилмент",
  )
  seller = models.OneToOneField(
    "sellers.Seller",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="user_account",
  )

  class Meta:
    verbose_name = "Пользователь"
    verbose_name_plural = "Пользователи"

  @property
  def is_admin(self):
    return self.role == self.Role.ADMIN

  @property
  def is_manager(self):
    return self.role == self.Role.MANAGER

  @property
  def is_seller_user(self):
    return self.role == self.Role.SELLER
