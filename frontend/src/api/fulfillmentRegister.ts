import { apiFetch } from './client'
import type { LoginResponse } from '../types/auth'

export type FulfillmentRegisterPayload = {
  fulfillment_name: string
  username: string
  password: string
  email?: string
}

export type FulfillmentRegisterResponse = LoginResponse & {
  fulfillment: {
    id: number
    name: string
    slug: string
  }
}

export async function registerFulfillment(payload: FulfillmentRegisterPayload): Promise<FulfillmentRegisterResponse> {
  return apiFetch<FulfillmentRegisterResponse>('/api/auth/fulfillment/register/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
