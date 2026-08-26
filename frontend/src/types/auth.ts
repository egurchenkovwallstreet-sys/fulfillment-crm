export type UserRole = 'admin' | 'manager' | 'seller'

export type User = {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  role: UserRole
  role_display: string
  seller: number | null
  seller_name: string | null
  wb_enabled?: boolean
  ozon_enabled?: boolean
  has_wb_token?: boolean
  has_ozon_api?: boolean
}

export type LoginResponse = {
  access: string
  refresh: string
  user: User
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Администратор',
  manager: 'Менеджер склада',
  seller: 'Селлер',
}
