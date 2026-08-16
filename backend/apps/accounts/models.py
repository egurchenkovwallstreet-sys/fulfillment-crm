from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
  class Role(models.TextChoices):
    ADMIN = "admin", "Администратор"
    MANAGER = "manager", "Менеджер"
    SELLER = "seller", "Селлер"

  role = models.CharField(
    max_length=20,
    choices=Role.choices,
    default=Role.MANAGER,
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
