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
    ledger: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    plan: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    approvals: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    audit: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    documents: vi.fn().mockResolvedValue([]),
  },
}))

import { router } from '@/app/router'
import { koshApi } from '@/lib/api/kosh'

describe('Kosh protected routes', () => {
  it('renders all five pages in the existing layout and loads the active seller', async () => {
    const pages = [
      ['/cash', 'Cash', 3, koshApi.ledger],
      ['/plan', 'Plan', 6, koshApi.plan],
      ['/approvals', 'Approvals', 6, koshApi.approvals],
      ['/audit', 'Audit', 7, koshApi.audit],
      ['/connect', 'Connect', 1, koshApi.documents],
    ] as const
    for (const [path, title, stage, load] of pages) {
      await router.navigate(path)
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
      expect(screen.getByText(`Coming in Stage ${stage}`)).toBeInTheDocument()
      expect(screen.getByRole('complementary', { name: 'Main navigation' })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'My Tenders' })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Seller Profile' })).toBeInTheDocument()
      await waitFor(() => expect(load).toHaveBeenCalledWith(7))
      cleanup()
      client.clear()
    }
  })
})
