/** Rendered React + real local API integration. Fixture tenders and development login;
 * no API responses, profile writes, matching, or authorization are mocked. */
import React from 'react'
import { beforeAll, afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

let auth: typeof import('../src/lib/auth')
let api: typeof import('../src/lib/api/client')
let sellersApi: typeof import('../src/lib/api/sellers')['sellersApi']
let portalApi: typeof import('../src/lib/api/portal')['portalApi']
let LoginPage: typeof import('../src/features/auth/LoginPage')['LoginPage']
let MyTendersPage: typeof import('../src/features/portal/MyTendersPage')['MyTendersPage']
let ProfilePage: typeof import('../src/features/profile/ProfilePage')['ProfilePage']
let TenderDetailPage: typeof import('../src/features/portal/TenderDetailPage')['TenderDetailPage']
let SellerProvider: typeof import('../src/app/SellerContext')['SellerProvider']
let RequireAuth: typeof import('../src/app/RequireAuth')['RequireAuth']
let AppLayout: typeof import('../src/components/layout/AppLayout')['AppLayout']
const evidence: Record<string, unknown> = {}

beforeAll(async () => {
  vi.stubEnv('DEV', true)
  vi.stubEnv('VITE_DEV_LOGIN', 'true')
  const fetchHttp = globalThis.fetch
  globalThis.fetch = (input, init) => fetchHttp(
    typeof input === 'string' && input.startsWith('/') ? `http://127.0.0.1:8000${input}` : input, init)
  auth = await import('../src/lib/auth')
  api = await import('../src/lib/api/client')
  api.apiClient.defaults.baseURL = 'http://127.0.0.1:8000/api'
  api.apiClient.defaults.adapter = 'http'
  sellersApi = (await import('../src/lib/api/sellers')).sellersApi
  portalApi = (await import('../src/lib/api/portal')).portalApi
  LoginPage = (await import('../src/features/auth/LoginPage')).LoginPage
  MyTendersPage = (await import('../src/features/portal/MyTendersPage')).MyTendersPage
  ProfilePage = (await import('../src/features/profile/ProfilePage')).ProfilePage
  TenderDetailPage = (await import('../src/features/portal/TenderDetailPage')).TenderDetailPage
  SellerProvider = (await import('../src/app/SellerContext')).SellerProvider
  RequireAuth = (await import('../src/app/RequireAuth')).RequireAuth
  AppLayout = (await import('../src/components/layout/AppLayout')).AppLayout
})

afterEach(() => { cleanup(); auth.signOut(); sessionStorage.clear(); localStorage.clear() })

function show(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/" element={<RequireAuth><SellerProvider><AppLayout /></SellerProvider></RequireAuth>}>
      <Route index element={<MyTendersPage />} />
      <Route path="profile" element={<ProfilePage />} />
      <Route path="tenders/:tenderId" element={<TenderDetailPage />} />
    </Route>
  </Routes></MemoryRouter></QueryClientProvider>)
}

async function profile(name: string, turnover?: string) {
  await auth.signIn(`validation-${name}-${Date.now()}@example.invalid`, '')
  const sellers = await sellersApi.list()
  const seller = sellers[0]
  await sellersApi.setAttribute(seller.id, { key: 'product_category', value_type: 'TEXT', value: 'Desktop Computers' })
  if (turnover !== undefined) await sellersApi.setAttribute(seller.id, {
    key: 'annual_turnover', value_type: 'NUMBER', value: turnover })
  await portalApi.refreshMatches(seller.id)
  return seller.id
}

describe('local portal with actual application services', () => {
  it('signs in through development UI and signs out', async () => {
    show('/login')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), `validation-login-${Date.now()}@example.invalid`)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('link', { name: 'Seller Profile' }, { timeout: 15000 })).toBeVisible()
    expect(auth.getSession()).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeVisible()
    expect(auth.getSession()).toBeNull()
  })

  it('shows matched tenders, filters, detail, documents, requirements and evidence', async () => {
    const sid = await profile('strong', '900000')
    const list = await portalApi.tenders(sid, { view: 'matched', live_only: true })
    expect(list.total).toBeGreaterThan(0)
    evidence.strong = { seller_id: sid, matched: list.total, tender_id: list.items[0].tender_id }
    show()
    expect(await screen.findByText('Matched open tenders', {}, { timeout: 15000 })).toBeVisible()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Matched', exact: true }))
    const link = await screen.findByRole('link', { name: list.items[0].bid_number })
    await user.click(link)
    expect(await screen.findByText('Your match', {}, { timeout: 15000 })).toBeVisible()
    const turnoverDisplays = screen.getAllByText(/Bidder Turnover Amount/i)
    expect(turnoverDisplays.length).toBeGreaterThanOrEqual(2)
    turnoverDisplays.forEach(node => expect(node).toBeVisible())
    expect(screen.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible()
    expect(screen.getByText('Package complete')).toBeVisible()
    expect(screen.getByText(/AI summary is currently unavailable/)).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Structured eligibility' })).toBeVisible()
    expect(screen.getAllByText(/7 lakh/i).length).toBeGreaterThan(0)
  })

  it('keeps incomplete seller outcomes in review and rejects cross-tenant API reads', async () => {
    const sid = await profile('incomplete')
    const summary = await portalApi.summary(sid)
    expect(summary.live_review_required).toBeGreaterThan(0)
    evidence.incomplete = { seller_id: sid, review: summary.live_review_required }
    const strong = evidence.strong as { seller_id: number; tender_id: number }
    await expect(sellersApi.get(strong.seller_id)).rejects.toMatchObject({ response: { status: 403 } })
    await expect(portalApi.tender(strong.seller_id, strong.tender_id)).rejects.toMatchObject({ response: { status: 403 } })
    show()
    await screen.findByText('Matched open tenders', {}, { timeout: 15000 })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Needs review', exact: true }))
    const review = await portalApi.tenders(sid, { view: 'review', live_only: true })
    expect(review.items.length).toBeGreaterThan(0)
    for (const tender of review.items) {
      expect(await screen.findByRole('link', { name: tender.bid_number })).toBeVisible()
    }
  })

  it('edits a profile through its rendered form and creates a new revision', async () => {
    await auth.signIn(`validation-edit-${Date.now()}@example.invalid`, '')
    const sid = (await sellersApi.list())[0].id
    const before = await sellersApi.get(sid)
    show('/profile')
    const input = await screen.findByLabelText('Products / categories', {}, { timeout: 15000 })
    fireEvent.change(input, { target: { value: 'Desktop Computers' } })
    fireEvent.submit(input.closest('form')!)
    expect(await screen.findByRole('status', {}, { timeout: 15000 })).toHaveTextContent('Saved. Matches were recalculated')
    const after = await sellersApi.get(sid)
    expect(after.active_revision!.revision_number).toBeGreaterThan(before.active_revision!.revision_number)
    expect(after.active_revision!.attributes.find(x => x.key === 'product_category')!.value_text).toBe('Desktop Computers')
  })

  it('keeps a second profile save successful during the match refresh cooldown', async () => {
    await auth.signIn(`validation-cooldown-${Date.now()}@example.invalid`, '')
    const sid = (await sellersApi.list())[0].id
    show('/profile')
    const categories = await screen.findByLabelText('Products / categories', {}, { timeout: 15000 })
    fireEvent.change(categories, { target: { value: 'Desktop Computers' } })
    fireEvent.submit(categories.closest('form')!)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved. Matches were recalculated'))
    const turnover = screen.getByLabelText('Annual turnover (INR)')
    fireEvent.change(turnover, { target: { value: '900000' } })
    fireEvent.submit(turnover.closest('form')!)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Profile saved. Refresh matches shortly'))
    const saved = await sellersApi.get(sid)
    expect(saved.active_revision!.attributes.find(x => x.key === 'annual_turnover')!.value_number).toBe(900000)
  })
})
