import type { CurrentStatus, MatchStatus } from '@/lib/api/portal'

export const MATCH_LABEL: Record<MatchStatus, string> = {
  MATCHED: 'Matched',
  REVIEW_REQUIRED: 'Needs review',
  NOT_MATCHED: 'Not matched',
}

export const MATCH_HELP: Record<MatchStatus, string> = {
  MATCHED: 'All known mandatory requirements are met and no unresolved blocker remains.',
  NOT_MATCHED: 'At least one known mandatory requirement explicitly fails. Review the reasons below.',
  REVIEW_REQUIRED: 'Information is missing, uncertain or needs documentary review. This is not an automatic rejection.',
}

const FRIENDLY: Record<string, string> = {
  MAIN_BID: 'Main bid', SPECIFICATION: 'Specification', BOQ: 'Bill of quantities',
  BUYER_ATC: 'Buyer conditions', ATC: 'Additional conditions', ANNEXURE: 'Annexure',
  CORRIGENDUM: 'Amendment', SUCCESS: 'Extracted', PARTIAL_SUCCESS: 'Extracted with review',
  PENDING: 'Awaiting processing', FAILED: 'Processing failed', DOWNLOAD_FAILED: 'Download unavailable',
  OCR_REQUIRED: 'Text recognition required', OCR_EMPTY: 'No readable text found',
  OCR_LANGUAGE_UNSUPPORTED: 'Document language needs review', NATIVE: 'Native text',
  MIXED: 'Native text and OCR', OCR: 'OCR text', COMPLETE: 'Complete',
  INCOMPLETE_DOWNLOAD_FAILED: 'A required document could not be downloaded',
  INCOMPLETE_UNCLASSIFIED_REFERENCE: 'A document reference needs review',
  INCOMPLETE_EXTRACTION_PARTIAL: 'Some extracted content needs review',
  INCOMPLETE_PENDING: 'Required document processing is pending',
  INCOMPLETE_UNSUPPORTED: 'A required format is not supported',
}

export const friendlyLabel = (value: string) => FRIENDLY[value] ?? value.toLowerCase().replace(/_/g, ' ')

export const MATCH_VARIANT: Record<MatchStatus, 'success' | 'warning' | 'error'> = {
  MATCHED: 'success',
  REVIEW_REQUIRED: 'warning',
  NOT_MATCHED: 'error',
}

export const STATUS_VARIANT: Record<CurrentStatus, 'success' | 'info' | 'neutral' | 'error'> = {
  LIVE: 'success',
  UPCOMING: 'info',
  CLOSED: 'neutral',
  CANCELLED: 'error',
  UNKNOWN: 'neutral',
}
