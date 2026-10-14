import {describe,it,expect} from 'vitest'
import {formatPaiseINR} from '@/lib/formatMoney'
describe('integer paise formatting',()=>{
 it('keeps cents exact for large, negative and zero integer values',()=>{
  expect(formatPaiseINR(9000000000000001)).toBe('?9,00,00,00,00,00,000.01')
  expect(formatPaiseINR(-12345)).toBe('-?123.45')
  expect(formatPaiseINR(0)).toBe('?0.00')
  expect(formatPaiseINR(null)).toBe('-')
  expect(formatPaiseINR(1.5)).toBe('-')
 })
})
