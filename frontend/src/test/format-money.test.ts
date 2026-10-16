import { describe, it, expect } from 'vitest'
import { formatPaiseINR, parseRupeesToPaise } from '@/lib/formatMoney'

describe('integer paise formatting', () => {
  it('keeps cents exact for large, negative and zero integer values', () => {
    expect(formatPaiseINR(9000000000000001)).toBe('\u20B99,00,00,00,00,00,000.01')
    expect(formatPaiseINR(-12345)).toBe('-\u20B9123.45')
    expect(formatPaiseINR(0)).toBe('\u20B90.00')
    expect(formatPaiseINR(null)).toBe('-')
    expect(formatPaiseINR(undefined)).toBe('-')
    expect(formatPaiseINR(1.5)).toBe('-')
  })
})

describe('parseRupeesToPaise parser', () => {
  it('handles null, undefined, empty and whitespace input as null', () => {
    expect(parseRupeesToPaise(null)).toBeNull()
    expect(parseRupeesToPaise(undefined)).toBeNull()
    expect(parseRupeesToPaise('')).toBeNull()
    expect(parseRupeesToPaise('   ')).toBeNull()
  })

  it('preserves strict explicit zero (0) distinct from blank/null', () => {
    expect(parseRupeesToPaise('0')).toBe(0)
    expect(parseRupeesToPaise('0.00')).toBe(0)
    expect(parseRupeesToPaise(0)).toBe(0)
    expect(parseRupeesToPaise('₹0')).toBe(0)
    expect(parseRupeesToPaise('₹0.00')).toBe(0)
  })

  it('parses typical Rupee amounts into exact integer paise without float errors', () => {
    expect(parseRupeesToPaise('1')).toBe(100)
    expect(parseRupeesToPaise('1.15')).toBe(115)
    expect(parseRupeesToPaise('50000')).toBe(5000000)
    expect(parseRupeesToPaise('1,25,000')).toBe(12500000)
    expect(parseRupeesToPaise('₹1,25,000.50')).toBe(12500050)
    expect(parseRupeesToPaise('Rs. 45000.25')).toBe(4500025)
    expect(parseRupeesToPaise('INR 10000')).toBe(1000000)
  })

  it('handles negative values correctly', () => {
    expect(parseRupeesToPaise('-500')).toBe(-50000)
    expect(parseRupeesToPaise('-12.34')).toBe(-1234)
  })

  it('handles numeric input', () => {
    expect(parseRupeesToPaise(125000)).toBe(12500000)
    expect(parseRupeesToPaise(99.99)).toBe(9999)
  })

  it('rejects invalid non-numeric strings safely', () => {
    expect(parseRupeesToPaise('abc')).toBeNull()
    expect(parseRupeesToPaise('12.34.56')).toBeNull()
    expect(parseRupeesToPaise('foo123')).toBeNull()
  })
})
