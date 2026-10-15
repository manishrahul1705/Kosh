import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { CashPage } from '@/features/kosh/CashPage'
import { RouteErrorBoundary } from '@/components/RouteErrorBoundary'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { koshApi } from '@/lib/api/kosh'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/app/SellerContext', () => ({
  useSeller: () => ({
    activeSellerId: 7,
    sellers: [{ id: 7, name: 'Test Seller' }],
    loading: false,
    error: null,
    setActiveSellerId: vi.fn(),
  }),
}))

vi.mock('@/lib/api/kosh', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/kosh')>()
  return {
    ...actual,
    koshApi: {
      ledger: vi.fn().mockResolvedValue({ seller_id: 7, totals: { open_receivables_paise: 0 }, items: [] }),
      forecast: vi.fn(),
      runForecast: vi.fn().mockResolvedValue({ run_id: 1 }),
      cashEvents: vi.fn().mockResolvedValue({ role: 'OWNER', items: [] }),
      analysis: vi.fn().mockResolvedValue({ dso_days: 45, dpo_days: 30, cash_conversion_cycle_days: 15, top_3_customer_share: 0.4 }),
      backtest: vi.fn().mockResolvedValue({ coverage_by_horizon: { '1': 0.85 } }),
      whatIf: vi.fn(),
      acknowledgeAlert: vi.fn(),
    },
  }
})

function renderWithClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('CashPage Regression & Robust State Handling', () => {
  beforeEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('handles unrun placeholder response (status: NOT_IMPLEMENTED) without crashing', async () => {
    // The exact response returned by GET /kosh/sellers/{id}/forecast/latest before a forecast run exists
    vi.mocked(koshApi.forecast).mockResolvedValueOnce({
      seller_id: 7,
      status: 'NOT_IMPLEMENTED',
      items: [],
    } as any)

    renderWithClient(<CashPage />)

    expect(await screen.findByText('No forecast has been generated')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run forecast' })).toBeInTheDocument()
    expect(screen.queryByText(/Cannot read properties of undefined/)).not.toBeInTheDocument()
  })

  it('triggers forecast simulation when Run forecast button is clicked on placeholder state', async () => {
    vi.mocked(koshApi.forecast).mockResolvedValue({
      seller_id: 7,
      status: 'NOT_IMPLEMENTED',
      items: [],
    } as any)

    renderWithClient(<CashPage />)

    const runBtn = await screen.findByRole('button', { name: 'Run forecast' })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(koshApi.runForecast).toHaveBeenCalledWith(7)
    })
  })

  it('displays loading state during initial fetch', () => {
    vi.mocked(koshApi.forecast).mockReturnValueOnce(new Promise(() => {}))

    renderWithClient(<CashPage />)

    expect(screen.getByLabelText('Loading')).toBeInTheDocument()
    expect(screen.queryByText('13-week cash forecast')).not.toBeInTheDocument()
  })

  it('handles backend API failure gracefully with error alert and retry button', async () => {
    vi.mocked(koshApi.forecast).mockRejectedValueOnce(new Error('500 Internal Server Error'))

    renderWithClient(<CashPage />)

    expect(await screen.findByText(/Failed to load cash forecast from server/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('handles malformed or incompatible backend response safely without crashing', async () => {
    // Server returned invalid response without run or weeks array
    vi.mocked(koshApi.forecast).mockResolvedValueOnce({
      seller_id: 7,
      status: 'SUCCESS',
      weeks: null,
    } as any)

    renderWithClient(<CashPage />)

    expect(await screen.findByText('Incompatible or malformed forecast data received')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regenerate forecast' })).toBeInTheDocument()
  })

  it('handles valid empty result (weeks: [])', async () => {
    vi.mocked(koshApi.forecast).mockResolvedValueOnce({
      seller_id: 7,
      run: { id: 1, buffer_paise: 100000000, as_of_date: '2026-10-15' },
      weeks: [],
      under_review_paise: 0,
      alert: null,
    } as any)

    renderWithClient(<CashPage />)

    expect(await screen.findByText('No weekly forecast projections generated.')).toBeInTheDocument()
  })

  it('renders full 13-week chart, assumption controls, and shortfall alert when forecast exists', async () => {
    vi.mocked(koshApi.forecast).mockResolvedValueOnce({
      seller_id: 7,
      run: {
        id: 1,
        as_of_date: '2026-10-15',
        buffer_paise: 100000000,
        horizon_weeks: 13,
        n_paths: 2000,
        seed: 42,
        include_forecast_sales: true,
        include_addon_events: true,
        include_customer_history: false,
        include_revenue_signal: false,
        status: 'SUCCESS',
      },
      weeks: [
        {
          week_index: 1,
          week_start: '2026-10-12',
          week_end: '2026-10-18',
          p10_closing_balance_paise: 80000000,
          p50_closing_balance_paise: 120000000,
          p90_closing_balance_paise: 150000000,
          expected_inflow_committed_paise: 50000000,
          expected_inflow_forecast_paise: 20000000,
          expected_outflow_committed_paise: 40000000,
          expected_outflow_forecast_paise: 10000000,
          prob_below_buffer: 0.6,
          expected_shortfall_paise: 20000000,
        },
      ],
      under_review_paise: 48000000,
      alert: {
        id: 1,
        week_index: 1,
        probability: 0.6,
        expected_shortfall_paise: 20000000,
        peak_expected_shortfall_paise: 20000000,
        causes: [
          {
            type: 'CUSTOMER',
            customer: 'ABC Industries',
            amount_paise: 140000000,
            contribution_paise: 10000000,
          },
        ],
        summary: 'Week 1: 60% chance below buffer',
      },
    } as any)

    renderWithClient(<CashPage />)

    expect(await screen.findByText('13-week cash forecast')).toBeInTheDocument()
    expect(screen.getByLabelText('Include forecast sales')).toBeChecked()
    expect(screen.getByText('Under review: ₹4,80,000.00 excluded')).toBeInTheDocument()
    expect(screen.getByText('Week 1: 60% chance below buffer')).toBeInTheDocument()
    expect(screen.getByText('ABC Industries')).toBeInTheDocument()
    expect(screen.getByText(/What-if/)).toBeInTheDocument()
  })

  it('renders ErrorBoundary with recovery options when an unexpected render error occurs', () => {
    const ProblemChild = () => {
      throw new Error('Simulated runtime error')
    }

    render(
      <ErrorBoundary>
        <ProblemChild />
      </ErrorBoundary>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Simulated runtime error')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Try again/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Dashboard/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Ledger/ })).toBeInTheDocument()
  })
})
