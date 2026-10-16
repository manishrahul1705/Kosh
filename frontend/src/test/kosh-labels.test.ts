import { describe, it, expect } from 'vitest'
import { formatEnumLabel } from '@/lib/koshLabels'

describe('formatEnumLabel', () => {
  it('maps raw status enums to human readable plain labels', () => {
    expect(formatEnumLabel('REVIEW_REQUIRED')).toBe('Needs review')
    expect(formatEnumLabel('REVIEW')).toBe('Needs review')
    expect(formatEnumLabel('NOT_MATCHED')).toBe('Not eligible')
    expect(formatEnumLabel('MATCHED')).toBe('Eligible')
    expect(formatEnumLabel('INSUFFICIENT')).toBe('Not enough options')
    expect(formatEnumLabel('STALE')).toBe('Out of date: re-run')
    expect(formatEnumLabel('PROPOSED')).toBe('Proposed')
    expect(formatEnumLabel('PENDING_APPROVAL')).toBe('Pending approval')
    expect(formatEnumLabel('OBLIGATION_CLUSTER')).toBe('Payments due together')
    expect(formatEnumLabel('SUPPLIER_PAYMENT')).toBe('Supplier payment')
    expect(formatEnumLabel('COLLECTION_FOLLOWUP')).toBe('Collection follow-up')
    expect(formatEnumLabel('TREDS_INVOICE_DISCOUNTING')).toBe('TReDS invoice discounting')
    expect(formatEnumLabel('CGTMSE_WORKING_CAPITAL')).toBe('CGTMSE credit guarantee')
    expect(formatEnumLabel('PROCESSED')).toBe('Processed clean')
  })

  it('handles null and undefined safely', () => {
    expect(formatEnumLabel(null)).toBe('-')
    expect(formatEnumLabel(undefined)).toBe('-')
    expect(formatEnumLabel('')).toBe('-')
  })

  it('replaces underscores for unknown enums', () => {
    expect(formatEnumLabel('CUSTOM_ACTION_STATUS')).toBe('CUSTOM ACTION STATUS')
  })
})
