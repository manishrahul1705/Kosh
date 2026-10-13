import { apiClient } from './client'

export interface KoshPlaceholder {
  seller_id: number
  status: 'NOT_IMPLEMENTED'
  items: Record<string, unknown>[]
}

export interface BusinessDocumentPlaceholder {
  id: number
  filename: string
}

export const koshApi = {
  ledger: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/ledger`).then((r) => r.data),
  forecast: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/forecast/latest`).then((r) => r.data),
  alerts: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/alerts`).then((r) => r.data),
  plan: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/plan`).then((r) => r.data),
  approvals: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/approvals`).then((r) => r.data),
  audit: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/audit`).then((r) => r.data),
  documents: (sellerId: number) =>
    apiClient.get<BusinessDocumentPlaceholder[]>(`/kosh/sellers/${sellerId}/documents`).then((r) => r.data),
}
