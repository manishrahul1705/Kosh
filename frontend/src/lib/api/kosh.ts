import { apiClient } from './client'

export interface KoshPlaceholder {
  seller_id: number
  status: 'NOT_IMPLEMENTED'
  items: Record<string, unknown>[]
}

export interface BusinessDocumentPlaceholder {
  id: number
  original_filename: string
  kind: string
  status: string
  status_reason?: string
}

export interface LedgerRow { id:number; direction:string; party:string; invoice_number:string; invoice_date:string; due_date:string; amount_paise:number; status:string; source_location?:string }
export interface Ledger { seller_id:number; totals:{ open_receivables_paise:number; open_payables_paise:number; overdue_receivables_paise:number; review_count:number; latest_bank_balance_paise:number|null; bank_balance_as_of:string|null }; items:LedgerRow[] }
export interface Consent { id:number; purpose:string; data_types:string[]; expires_at:string; status:string }
export interface AuditResponse { seller_id:number; status:string; items:{sequence:number;recorded_at:string;actor_type:string;action:string;tier:string;policy_decision:string}[] }
export interface ForecastWeek { week_index:number;week_start:string;week_end:string;p10_closing_balance_paise:number;p50_closing_balance_paise:number;p90_closing_balance_paise:number;expected_inflow_committed_paise:number;expected_inflow_forecast_paise:number;expected_outflow_committed_paise:number;expected_outflow_forecast_paise:number;prob_below_buffer:number;expected_shortfall_paise:number }
export interface ForecastAlert { id?:number;week_index:number;probability:number;expected_shortfall_paise:number;peak_expected_shortfall_paise:number;causes:{type:string;customer?:string;counterparty_id?:number;invoice_numbers?:string[];amount_paise:number;contribution_paise:number}[];summary?:string;status?:string }
export interface Forecast { seller_id:number;run:{id:number;as_of_date:string;buffer_paise:number;include_forecast_sales?:boolean};weeks:ForecastWeek[];under_review_paise:number;alert:ForecastAlert|null }

export const koshApi = {
  ledger: (sellerId: number) =>
    apiClient.get<Ledger>(`/kosh/sellers/${sellerId}/ledger`).then((r) => r.data),
  forecast: (sellerId: number) => apiClient.get<Forecast>(`/kosh/sellers/${sellerId}/forecast/latest`).then((r) => r.data),
  runForecast: (sellerId:number,payload:Record<string,unknown>={}) => apiClient.post(`/kosh/sellers/${sellerId}/forecast/run`,payload).then(r=>r.data),
  whatIf: (sellerId:number,payload:Record<string,unknown>) => apiClient.post<Forecast>(`/kosh/sellers/${sellerId}/forecast/whatif`,payload).then(r=>r.data),
  acknowledgeAlert: (sellerId:number,id:number) => apiClient.post(`/kosh/sellers/${sellerId}/alerts/${id}/acknowledge`).then(r=>r.data),
  backtest: (sellerId:number) => apiClient.get<Record<string,unknown>>(`/kosh/sellers/${sellerId}/forecast/backtest/latest`).then(r=>r.data),
  runBacktest: (sellerId:number) => apiClient.post(`/kosh/sellers/${sellerId}/forecast/backtest`).then(r=>r.data),
  analysis: (sellerId:number) => apiClient.get<Record<string,unknown>>(`/kosh/sellers/${sellerId}/analysis`).then(r=>r.data),
  alerts: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/alerts`).then((r) => r.data),
  plan: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/plan`).then((r) => r.data),
  approvals: (sellerId: number) =>
    apiClient.get<KoshPlaceholder>(`/kosh/sellers/${sellerId}/approvals`).then((r) => r.data),
  audit: (sellerId: number) =>
    apiClient.get<AuditResponse>(`/kosh/sellers/${sellerId}/audit`).then((r) => r.data),
  documents: (sellerId: number) =>
    apiClient.get<BusinessDocumentPlaceholder[]>(`/kosh/sellers/${sellerId}/documents`).then((r) => r.data),
  consents: (sellerId:number) => apiClient.get<Consent[]>(`/kosh/sellers/${sellerId}/consents`).then(r=>r.data),
  createConsent: (sellerId:number,payload:Record<string,unknown>) => apiClient.post(`/kosh/sellers/${sellerId}/consents`,payload).then(r=>r.data),
  revokeConsent: (sellerId:number,id:number) => apiClient.post(`/kosh/sellers/${sellerId}/consents/${id}/revoke`).then(r=>r.data),
  uploadDocument: (sellerId:number,kind:string,file:File) => { const body=new FormData();body.append('kind',kind);body.append('file',file);return apiClient.post(`/kosh/sellers/${sellerId}/documents`,body).then(r=>r.data) },
  processDocument: (sellerId:number,id:number) => apiClient.post(`/kosh/sellers/${sellerId}/documents/${id}/process`).then(r=>r.data),
  verifyAudit: (sellerId:number) => apiClient.get<{valid:boolean;entries:number;reason?:string}>(`/kosh/sellers/${sellerId}/audit/verify`).then(r=>r.data),
  patchInvoice: (sellerId:number,id:number,payload:Record<string,unknown>) => apiClient.patch(`/kosh/sellers/${sellerId}/invoices/${id}`,payload).then(r=>r.data),
  obligations: (sellerId:number) => apiClient.get<Record<string,unknown>[]>(`/kosh/sellers/${sellerId}/obligations`).then(r=>r.data),
}
