import { apiClient } from './client'

// Mirrors app/api/portal.py. Every call is scoped to one seller the signed-in user belongs to;
// the backend enforces membership on each request.

export type MatchStatus = 'MATCHED' | 'NOT_MATCHED' | 'REVIEW_REQUIRED'
export type CurrentStatus = 'LIVE' | 'UPCOMING' | 'CLOSED' | 'CANCELLED' | 'UNKNOWN'

export interface MatchInfo {
  match_status: MatchStatus
  relevance_status: string
  eligibility_status: string | null
  matched_terms: string[]
  requirements_passed: number
  requirements_failed: number
  requirements_needing_review: number
  computed_at: string | null
}

export interface Reason {
  requirement: string
  requirement_type: string
  detail: string
  relaxation_applied?: string | null
}

export interface TenderCard {
  tender_id: number
  bid_number: string
  title: string | null
  buyer_name: string | null
  ministry: string | null
  department: string | null
  category: string | null
  quantity: number | null
  bid_start_at: string | null
  bid_end_at: string | null
  days_to_deadline: number | null
  current_status: CurrentStatus
  last_updated_at: string | null
  match: MatchInfo
}

export interface TenderPage {
  items: TenderCard[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface PortalSummary {
  seller_id: number
  live_matched: number
  live_review_required: number
  live_not_matched: number
  closing_within_3_days: number
  matching_terms: string[]
  last_matched_at: string | null
  guidance: string[]
}

export interface Evidence {
  source_location?: { kind?: string; sheet?: string; table?: number; cell_range?: (string | null)[][] } | null
  document_id: number | null
  document_type: string | null
  document_name: string | null
  page: number | null
  section: string | null
  quote: string
}

export interface Requirement {
  requirement_type: string
  category: string
  title: string
  summary: string | null
  obligation_level: string
  condition: string | null
  value_text: string | null
  value_number: number | null
  unit: string | null
  ambiguity: string | null
  risk_flags: string[]
  review_required: boolean
  evidence: Evidence[]
}

export interface DocumentVersionInfo {
  file_type?: string | null
  processing_state?: string
  extraction_state?: string | null
  extraction_quality?: string | null
  extraction_error?: string | null
  version_id: number
  version_number: number
  sha256: string | null
  file_size: number | null
  mime_type: string | null
  downloaded_at: string | null
  validation_status: string
  downloadable: boolean
}

export interface TenderDocumentInfo {
  processing_state?: string
  document_id: number
  document_type: string
  display_name: string | null
  filename: string | null
  source_url: string | null
  is_active: boolean
  discovered_at: string | null
  current_version_id: number | null
  versions: DocumentVersionInfo[]
}

export interface TenderDetail {
  basic: {
    tender_id: number
    bid_number: string
    title: string | null
    bid_type: string | null
    buyer_name: string | null
    ministry: string | null
    department: string | null
    organisation: string | null
    category: string | null
    quantity: number | null
    estimated_value: string | null
    bid_start_at: string | null
    bid_end_at: string | null
    bid_opening_at: string | null
    source_url: string | null
  }
  status: {
    current_status: CurrentStatus
    status_source: string | null
    source_reported_status: string
    last_status_check_at: string | null
    last_seen_on_gem_at: string | null
    last_updated_at: string | null
  }
  summary: string | null
  analysis_status: string
  package?: { complete: boolean; completeness: string; reasons: { state: string; reference_id?: number; document_id?: number }[]; relevant_document_count: number; missing_reference_count: number }
  deterministic_requirements?: Requirement[]
  eligibility: Requirement[]
  technical_requirements: Requirement[]
  important_conditions: Requirement[]
  extracted_fields: { field: string; group: string; status: string; value: string | null; number: number | null; flag: string | null; unit: string | null }[]
  review_flags: { flag_type: string; severity: string; message: string }[]
  amendments: {
    amended: boolean
    field_changes: { field: string; old: string | null; new: string | null; detected_at: string | null }[]
    changed_documents: { document_id: number; document_type: string; name: string | null; versions: number }[]
    status_history: { old: string | null; new: string; reason: string; detected_at: string | null }[]
  }
  documents: TenderDocumentInfo[]
  match: MatchInfo & { reasons: { matched: Reason[]; failed: Reason[]; needs_review: Reason[]; info: Reason[] } }
}

export interface TenderFilters {
  view?: 'actionable' | 'matched' | 'review' | 'not_matched' | 'all'
  live_only?: boolean
  closing_within_days?: number
  category?: string
  buyer?: string
  q?: string
  page?: number
  page_size?: number
}

export const portalApi = {
  summary: (sellerId: number) =>
    apiClient.get<PortalSummary>(`/portal/sellers/${sellerId}/summary`).then((r) => r.data),

  tenders: (sellerId: number, filters: TenderFilters) =>
    apiClient.get<TenderPage>(`/portal/sellers/${sellerId}/tenders`, { params: filters }).then((r) => r.data),

  tender: (sellerId: number, tenderId: number) =>
    apiClient.get<TenderDetail>(`/portal/sellers/${sellerId}/tenders/${tenderId}`).then((r) => r.data),

  refreshMatches: (sellerId: number) =>
    apiClient.post(`/portal/sellers/${sellerId}/matches/refresh`).then((r) => r.data),

  /** Authenticated download (a plain link cannot carry the bearer token). */
  async downloadDocument(sellerId: number, tenderId: number, documentId: number, versionId: number, filename: string) {
    const res = await apiClient.get<Blob>(
      `/portal/sellers/${sellerId}/tenders/${tenderId}/documents/${documentId}/versions/${versionId}/download`,
      { responseType: 'blob' },
    )
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },
}
