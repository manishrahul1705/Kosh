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
export interface ForecastWeek { expected_inflow_addon_paise?:number;expected_outflow_addon_paise?:number; expected_inflow_sandbox_paise?:number;expected_outflow_sandbox_paise?:number; week_index:number;week_start:string;week_end:string;p10_closing_balance_paise:number;p50_closing_balance_paise:number;p90_closing_balance_paise:number;expected_inflow_committed_paise:number;expected_inflow_forecast_paise:number;expected_outflow_committed_paise:number;expected_outflow_forecast_paise:number;prob_below_buffer:number;expected_shortfall_paise:number }
export interface ForecastAlert { id?:number;week_index:number;probability:number;expected_shortfall_paise:number;peak_expected_shortfall_paise:number;causes:{type:string;customer?:string;counterparty_id?:number;invoice_numbers?:string[];amount_paise:number;contribution_paise:number}[];summary?:string;status?:string }
export interface Forecast { seller_id:number;run:{id:number;n_paths?:number;seed?:number;include_addon_events?:boolean;as_of_date:string;buffer_paise:number;include_forecast_sales?:boolean};weeks:ForecastWeek[];under_review_paise:number;alert:ForecastAlert|null }
export interface FinancingOption { invoice_eligibility?:{scope:string;status:string;eligible:boolean;max_amount_paise:number;reasons:{criterion:string;reason:string;reason_code:string;status:string}[];evidence:{invoice_number?:string;buyer?:string;due_date?:string}[]}[]; quote_basis:string; amount_paise:number;days:number;cost_paise:number;cost_assumption:string; product_id:string;display_name:string;provider_label:string;scope:string|null;status:'MATCHED'|'NOT_MATCHED'|'REVIEW_REQUIRED';max_amount_paise:number;effective_annual_rate:string|null;arrival_business_days:number;reasons:{reason:string;reason_code:string;product_clause?:{quote?:string}}[];evidence:Record<string,unknown>[];assumption:boolean;verify_before_relying:boolean }
export interface FinancingOptions { seller_id:number;sort_rule:string;items:FinancingOption[] }
export interface SafetyPlan { target_probability:string;status:string;total_cost_paise:number;alert_week_probability:number;lines:{product_id:string;amount_paise:number;days:number;cost_paise:number}[] }
export interface FinancingPlan { target_probability:string;planning_details:{baseline_status:string}; why_this_plan:string; id:number;status:string;method:string;total_cost_paise:number;baseline_cost_paise:number;before_probabilities:number[];after_probabilities:number[];lines:{id:number;product_id:string;amount_paise:number;arrival_week:number;cost_paise:number;required_tier:string;days:number;funding_date:string;repayment_date:string|null;repayment_assumption:string}[] }

export interface ActionIntent { id:string; plan_line_id:number|null; action_type:string; tier:string; params:Record<string,unknown>; status:string; expires_at:string|null; policy_decision:Record<string,unknown> }
export interface SandboxItem { id:string|number; intent_id:string; status:string; [key:string]:unknown }
export const koshApi = {
  operations:(id:number)=>apiClient.get<{role:string;items:{id:number;kind:string;status:string;evidence_ref:string;data:Record<string,unknown>}[];counterparties:{id:number;name:string;kind:string}[];market_sample:{material_code:string;change_percent:string;source:string}[]}>(`/kosh/sellers/${id}/operations`).then(r=>r.data),
  orderProposal:(id:number,payload:Record<string,unknown>)=>apiClient.post(`/kosh/sellers/${id}/operations/orders`,payload).then(r=>r.data),
  confirmOrder:(id:number,record:number)=>apiClient.post(`/kosh/sellers/${id}/operations/orders/${record}/confirm`).then(r=>r.data),
  priceProposal:(id:number,payload:Record<string,unknown>)=>apiClient.post(`/kosh/sellers/${id}/operations/pricing`,payload).then(r=>r.data),
  rfqDraft:(id:number,payload:Record<string,unknown>)=>apiClient.post<{id:number;body:string}>(`/kosh/sellers/${id}/operations/rfqs`,payload).then(r=>r.data),
  operationIntent:(id:number,draft:number)=>apiClient.post(`/kosh/sellers/${id}/operations/drafts/${draft}/intent`).then(r=>r.data),
  collections:(id:number)=>apiClient.get<{role:string;items:{invoice_id:number;invoice_number:string;party:string;amount_paise:number;interest:{status:string;interest_paise:number|null;annual_rate:string;reason:string}}[]}>(`/kosh/sellers/${id}/collections`).then(r=>r.data),
  collectionTerms:(id:number,invoice:number,payload:Record<string,unknown>)=>apiClient.put(`/kosh/sellers/${id}/collections/${invoice}/terms`,payload).then(r=>r.data),
  reminderDraft:(id:number,invoice:number,tone:string)=>apiClient.post<{id:number;body:string}>(`/kosh/sellers/${id}/collections/drafts`,{invoice_id:invoice,tone}).then(r=>r.data),
  reminderIntent:(id:number,draft:number)=>apiClient.post(`/kosh/sellers/${id}/collections/drafts/${draft}/intent`).then(r=>r.data),
  cashEvents:(sellerId:number)=>apiClient.get<{role:string;items:{id:number;event_type:string;source_module:string;evidence_ref:string;event_date:string;amount_paise:number;status:string}[]}>(`/kosh/sellers/${sellerId}/cash-events`).then(r=>r.data),
  proposeCashEvent:(sellerId:number,payload:Record<string,unknown>)=>apiClient.post(`/kosh/sellers/${sellerId}/cash-events`,payload).then(r=>r.data),
  confirmCashEvent:(sellerId:number,id:number)=>apiClient.post(`/kosh/sellers/${sellerId}/cash-events/${id}/confirm`).then(r=>r.data),
  actionInbox:(sellerId:number)=>apiClient.get<{role:string;items:ActionIntent[]}>(`/kosh/sellers/${sellerId}/actions/intents`).then(r=>r.data),
  proposeIntent:(sellerId:number,planLineId:number)=>apiClient.post(`/kosh/sellers/${sellerId}/actions/intents`,{plan_line_id:planLineId}).then(r=>r.data),
  approveIntent:(sellerId:number,id:string,otp?:string)=>apiClient.post<{approval_token:string;expires_at:string}>(`/kosh/sellers/${sellerId}/actions/intents/${id}/approve`,otp?{otp_code:otp}:{}).then(r=>r.data),
  rejectIntent:(sellerId:number,id:string)=>apiClient.post(`/kosh/sellers/${sellerId}/actions/intents/${id}/reject`).then(r=>r.data),
  requestOtp:(sellerId:number,id:string)=>apiClient.post(`/kosh/sellers/${sellerId}/actions/intents/${id}/otp`).then(r=>r.data),
  executeIntent:(sellerId:number,id:string,token:string)=>apiClient.post(`/kosh/sellers/${sellerId}/actions/intents/${id}/execute`,{approval_token:token}).then(r=>r.data),
  policy:(sellerId:number)=>apiClient.get<{role:string;seller_kill:boolean;global_kill:boolean}>(`/kosh/sellers/${sellerId}/policy`).then(r=>r.data),
  killSwitch:(sellerId:number,enabled:boolean)=>apiClient.post(`/kosh/sellers/${sellerId}/policy/kill-switch`,{enabled,scope:'SELLER'}).then(r=>r.data),
  sandboxInbox:(sellerId:number)=>apiClient.get<{items:SandboxItem[]}>(`/kosh/sellers/${sellerId}/sandbox/inbox`).then(r=>r.data),
  sandboxOutbox:(sellerId:number)=>apiClient.get<{items:SandboxItem[]}>(`/kosh/sellers/${sellerId}/sandbox/outbox`).then(r=>r.data),
  executions:(sellerId:number)=>apiClient.get<{items:SandboxItem[]}>(`/kosh/sellers/${sellerId}/sandbox/executions`).then(r=>r.data),
  blockedDocumentPayment:(sellerId:number)=>apiClient.post(`/kosh/sellers/${sellerId}/actions/intents`,{source:'DOCUMENT',action_type:'PAYMENT',amount_paise:48000000,payee:'XXXX'}).then(r=>r.data),
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
  financingOptions:(sellerId:number)=>apiClient.get<FinancingOptions>(`/kosh/sellers/${sellerId}/financing/options`).then(r=>r.data),
  evaluateFinancing:(sellerId:number)=>apiClient.post(`/kosh/sellers/${sellerId}/financing/evaluate`).then(r=>r.data),
  latestPlan:(sellerId:number)=>apiClient.get<FinancingPlan>(`/kosh/sellers/${sellerId}/plans/latest`).then(r=>r.data),
  safetyCurve:(sellerId:number)=>apiClient.get<{items:SafetyPlan[]}>(`/kosh/sellers/${sellerId}/financing/safety-curve`).then(r=>r.data),
  createPlan:(sellerId:number,targetProbability="0.20")=>apiClient.post(`/kosh/sellers/${sellerId}/plans`,{target_probability:targetProbability}).then(r=>r.data),
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
  securityEvents:(sellerId:number)=>apiClient.get<{counts:Record<string,number>}>(`/kosh/sellers/${sellerId}/audit/security-events`).then(r=>r.data),
  exportAudit:(sellerId:number)=>apiClient.get<string>(`/kosh/sellers/${sellerId}/audit/export`,{responseType:'text'}).then(r=>r.data),
  verifyAuditExport:(sellerId:number,jsonl:string)=>apiClient.post<{valid:boolean;reason?:string}>(`/kosh/sellers/${sellerId}/audit/verify-export`,{jsonl}).then(r=>r.data),
  verifyAudit: (sellerId:number) => apiClient.get<{valid:boolean;entries:number;reason?:string}>(`/kosh/sellers/${sellerId}/audit/verify`).then(r=>r.data),
  patchInvoice: (sellerId:number,id:number,payload:Record<string,unknown>) => apiClient.patch(`/kosh/sellers/${sellerId}/invoices/${id}`,payload).then(r=>r.data),
  obligations: (sellerId:number) => apiClient.get<Record<string,unknown>[]>(`/kosh/sellers/${sellerId}/obligations`).then(r=>r.data),
}
