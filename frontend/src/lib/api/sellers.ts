import { apiClient } from './client'

export interface SellerSummary {
  id: number
  name: string
  organization_id: string | null
  active_revision_id: number | null
  revision_number: number | null
  fingerprint: string | null
  created_at: string
}

export interface SellerAttribute {
  key: string
  value_type: string
  value_text: string | null
  value_number: number | null
  value_json: string | null
  context: string | null
}

export interface SellerDocument {
  document_type: string
  display_name: string
  filename: string
  issue_date: string | null
  expiry_date: string | null
  status: string
}

export interface SellerDetail {
  id: number
  name: string
  organization_id: string | null
  active_revision: {
    id: number
    revision_number: number
    fingerprint: string
    comment: string | null
    created_at: string
    attributes: SellerAttribute[]
    documents: SellerDocument[]
  } | null
}

export const sellersApi = {
  provision: () => apiClient.post<{ user_id: number }>('/auth/provision').then((r) => r.data),

  list: () => apiClient.get<SellerSummary[]>('/sellers').then((r) => r.data),

  get: (id: number) => apiClient.get<SellerDetail>(`/sellers/${id}`).then((r) => r.data),

  setAttribute: (id: number, attr: { key: string; value_type: 'TEXT' | 'NUMBER' | 'BOOLEAN'; value: string }) => {
    const form = new FormData()
    form.append('key', attr.key)
    form.append('value_type', attr.value_type)
    if (attr.value_type === 'NUMBER') form.append('value_number', attr.value)
    else form.append('value_text', attr.value)
    return apiClient
      .post(`/sellers/${id}/attributes`, form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then((r) => r.data)
  },
}
