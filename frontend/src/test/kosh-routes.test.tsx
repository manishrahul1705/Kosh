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
      ['/cash', 'Cash', 3, koshApi.ledger],
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
