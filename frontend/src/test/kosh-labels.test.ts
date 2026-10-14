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
