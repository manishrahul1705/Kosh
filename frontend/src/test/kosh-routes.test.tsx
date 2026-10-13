import { describe, it, expect, vi } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import type { ReactNode } from 'react'

vi.mock('@/lib/auth', async (original) => ({
  ...await original<typeof import('@/lib/auth')>(),
  getSession: () => ({ accessToken: 'test-session', refreshToken: '', expiresAt: Infinity, email: 'test@example.local' }),
}))
vi.mock('@/app/SellerContext', () => ({
  SellerProvider: ({ children }: { children: ReactNode }) => children,
  useSeller: () => ({ activeSellerId: 7, sellers: [{ id: 7, name: 'Test business' }], loading: false, error: null, setActiveSellerId: vi.fn() }),
}))
vi.mock('@/lib/api/kosh', () => ({
  koshApi: {
    ledger: vi.fn().mockResolvedValue({ seller_id: 7, totals: { open_receivables_paise:0,open_payables_paise:0,overdue_receivables_paise:0,review_count:0,latest_bank_balance_paise:null,bank_balance_as_of:null }, items: [] }),
    forecast: vi.fn().mockResolvedValue({seller_id:7,run:{id:1,as_of_date:'2026-10-13',buffer_paise:100000000,include_forecast_sales:true},weeks:[{week_index:1,week_start:'2026-10-12',week_end:'2026-10-18',p10_closing_balance_paise:80000000,p50_closing_balance_paise:120000000,p90_closing_balance_paise:150000000,expected_inflow_committed_paise:1,expected_inflow_forecast_paise:2,expected_outflow_committed_paise:3,expected_outflow_forecast_paise:4,prob_below_buffer:.6,expected_shortfall_paise:20000000}],under_review_paise:48000000,alert:{id:1,week_index:1,probability:.6,expected_shortfall_paise:20000000,peak_expected_shortfall_paise:20000000,causes:[{type:'CUSTOMER',customer:'ABC Industries',amount_paise:140000000,contribution_paise:10000000}],summary:'Week 1 warning'}}),
    analysis:vi.fn().mockResolvedValue({dso_days:60,dpo_days:42,cash_conversion_cycle_days:18,top_3_customer_share:.5}),backtest:vi.fn().mockResolvedValue({coverage_by_horizon:{'1':.8}}),runForecast:vi.fn(),whatIf:vi.fn(),acknowledgeAlert:vi.fn(),
    plan: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    approvals: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    audit: vi.fn().mockResolvedValue({ seller_id: 7, status: 'READY', items: [] }),
    documents: vi.fn().mockResolvedValue([]),
    consents: vi.fn().mockResolvedValue([]),
    verifyAudit: vi.fn().mockResolvedValue({valid:true,entries:0}),
    processDocument: vi.fn(),uploadDocument:vi.fn(),createConsent:vi.fn(),revokeConsent:vi.fn(),patchInvoice:vi.fn(),obligations:vi.fn().mockResolvedValue([]),
  },
}))

import { router } from '@/app/router'
import { koshApi } from '@/lib/api/kosh'

describe('Kosh protected routes', () => {
  it('renders Kosh pages in the existing layout and loads the active seller', async () => {
    const pages = [
      ['/cash', 'Cash forecast', null, koshApi.forecast],
      ['/ledger', 'Ledger', null, koshApi.ledger],
      ['/plan', 'Plan', 6, koshApi.plan],
      ['/approvals', 'Approvals', 6, koshApi.approvals],
      ['/audit', 'Audit', null, koshApi.audit],
      ['/connect', 'Connect', null, koshApi.documents],
    ] as const
    for (const [path, title, stage, load] of pages) {
      await router.navigate(path)
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
      if(stage!==null)expect(screen.getByText(`Coming in Stage ${stage}`)).toBeInTheDocument()
      expect(screen.getByRole('complementary', { name: 'Main navigation' })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'My Tenders' })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Seller Profile' })).toBeInTheDocument()
      await waitFor(() => expect(load).toHaveBeenCalledWith(7))
      cleanup()
      client.clear()
    }
  })
})
