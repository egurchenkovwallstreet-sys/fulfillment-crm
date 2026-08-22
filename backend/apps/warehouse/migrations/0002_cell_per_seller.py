from django.db import migrations, models
import django.db.models.deletion


def _cell_sort_key(number: str) -> tuple:
  number = (number or "").strip()
  if number.isdigit():
    return (0, int(number))
  return (1, number)


def migrate_cells_per_seller(apps, schema_editor):
  Cell = apps.get_model("warehouse", "Cell")
  Product = apps.get_model("warehouse", "Product")
  PickListItem = apps.get_model("orders", "PickListItem")

  old_to_new: dict[int, int] = {}

  seller_cell_ids: dict[int, set[int]] = {}
  for row in Product.objects.values_list("seller_id", "cell_id"):
    seller_id, cell_id = row
    seller_cell_ids.setdefault(seller_id, set()).add(cell_id)

  for seller_id, old_ids in seller_cell_ids.items():
    old_cells = list(Cell.objects.filter(id__in=old_ids))
    old_cells.sort(key=lambda cell: _cell_sort_key(cell.number))
    for idx, old_cell in enumerate(old_cells, start=1):
      new_cell = Cell.objects.create(
        seller_id=seller_id,
        number=str(idx),
        is_occupied=True,
      )
      old_to_new[old_cell.id] = new_cell.id
      Product.objects.filter(seller_id=seller_id, cell_id=old_cell.id).update(
        cell_id=new_cell.id,
      )

  for old_id, new_id in old_to_new.items():
    PickListItem.objects.filter(cell_id=old_id).update(cell_id=new_id)

  for item in PickListItem.objects.filter(cell__seller__isnull=True).iterator():
    product = Product.objects.filter(pk=item.product_id).first()
    if product and product.cell_id:
      PickListItem.objects.filter(pk=item.pk).update(cell_id=product.cell_id)

  PickListItem.objects.filter(cell__seller__isnull=True).delete()
  Cell.objects.filter(seller__isnull=True).delete()


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0001_initial"),
    ("warehouse", "0001_initial"),
    ("orders", "0001_initial"),
  ]

  operations = [
    migrations.AlterField(
      model_name="cell",
      name="number",
      field=models.CharField(max_length=50, verbose_name="Номер ячейки"),
    ),
    migrations.AddField(
      model_name="cell",
      name="seller",
      field=models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="cells",
        to="sellers.seller",
        verbose_name="Селлер",
      ),
    ),
    migrations.RunPython(migrate_cells_per_seller, migrations.RunPython.noop),
    migrations.AlterField(
      model_name="cell",
      name="seller",
      field=models.ForeignKey(
        on_delete=django.db.models.deletion.CASCADE,
        related_name="cells",
        to="sellers.seller",
        verbose_name="Селлер",
      ),
    ),
    migrations.AlterUniqueTogether(
      name="cell",
      unique_together={("seller", "number")},
    ),
  ]
