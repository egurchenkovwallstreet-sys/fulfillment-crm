from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
  help = "Переименовать логин пользователя (username)"

  def add_arguments(self, parser):
    parser.add_argument("--from", dest="old_username", required=True, help="Текущий логин")
    parser.add_argument("--to", dest="new_username", required=True, help="Новый логин")
    parser.add_argument(
      "--set-email",
      action="store_true",
      help="Также записать новый логин в поле email, если email пустой",
    )

  def handle(self, *args, **options):
    old = options["old_username"].strip()
    new = options["new_username"].strip()
    if not old or not new:
      raise CommandError("Укажите --from и --to")

    user = User.objects.filter(username=old).first()
    if not user:
      raise CommandError(f"Пользователь «{old}» не найден")

    if User.objects.filter(username=new).exclude(pk=user.pk).exists():
      raise CommandError(f"Логин «{new}» уже занят")

    user.username = new
    update_fields = ["username"]
    if options["set_email"] and not user.email:
      user.email = new
      update_fields.append("email")
    user.save(update_fields=update_fields)

    self.stdout.write(
      self.style.SUCCESS(
        f"Готово: «{old}» → «{new}» (роль: {user.get_role_display()}, id={user.pk})"
      )
    )
