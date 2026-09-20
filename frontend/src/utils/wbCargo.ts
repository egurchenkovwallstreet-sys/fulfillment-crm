const CARGO_LABELS: Record<number, string> = {
  1: 'МГТ',
  2: 'СГТ',
  3: 'КГТ+',
}

const DELIVERY_LABELS: Record<number, string> = {
  1: 'FBS',
  2: 'DBS',
  3: 'DBW',
  5: 'C&C',
  6: 'EDBS',
}

export function cargoTypeLabel(value?: number | null): string {
  if (!value) return ''
  return CARGO_LABELS[value] ?? `тип ${value}`
}

export function wbWarehouseLabel(warehouse: {
  name?: string
  wb_warehouse_id?: number
  cargo_type?: number | null
  delivery_type?: number | null
}): string {
  const name = warehouse.name || `Склад #${warehouse.wb_warehouse_id ?? '—'}`
  const cargo = cargoTypeLabel(warehouse.cargo_type)
  if (!cargo) return name
  const delivery =
    warehouse.delivery_type && warehouse.delivery_type !== 1
      ? DELIVERY_LABELS[warehouse.delivery_type] ?? `доставка ${warehouse.delivery_type}`
      : ''
  return delivery ? `${name} · ${delivery} · ${cargo}` : `${name} · ${cargo}`
}
