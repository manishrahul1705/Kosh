import { describe,expect,it } from 'vitest'
import { formatPaiseINR } from '@/lib/formatMoney'

describe('formatPaiseINR',()=>{
  it('formats integer paise with Indian grouping',()=>expect(formatPaiseINR(12345678)).toMatch(/1,23,456\.78/))
  it('preserves zero and renders missing values',()=>{expect(formatPaiseINR(0)).toMatch(/0\.00/);expect(formatPaiseINR(null)).toBe('-')})
})
