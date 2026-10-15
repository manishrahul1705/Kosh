import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  AlertTriangle,
  TrendingUp,
  Sliders,
  RotateCcw,
  Shield,
  Layers,
  ArrowRight,
  Info,
  Calendar,
  CheckCircle2,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { koshApi, Forecast } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'

const lakh = (value: number) => `₹${(value / 10_000_000).toFixed(1)}L`

export const CashPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [showForecast, setShowForecast] = useState(true)
  const [drawer, setDrawer] = useState(false)
  const [shift, setShift] = useState(0)
  const [scenario, setScenario] = useState<Forecast | null>(null)

  useQuery({
    queryKey: ['kosh', 'ledger', activeSellerId],
    queryFn: () => koshApi.ledger(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const forecast = useQuery({
    queryKey: ['kosh', 'forecast', activeSellerId],
    queryFn: () => koshApi.forecast(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
  })

  const events = useQuery({
    queryKey: ['kosh', 'cash-events', activeSellerId],
    queryFn: () => koshApi.cashEvents(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const analysis = useQuery({
    queryKey: ['kosh', 'analysis', activeSellerId],
    queryFn: () => koshApi.analysis(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const backtest = useQuery({
    queryKey: ['kosh', 'backtest', activeSellerId],
    queryFn: () => koshApi.backtest(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
  })

  const run = useMutation({
    mutationFn: () => koshApi.runForecast(activeSellerId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kosh', 'forecast', activeSellerId] }),
  })

  if (forecast.isLoading) return <PageLoader />
  if (forecast.isError)
    return (
      <section className="space-y-4">
        <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Cash</h2>
        <ErrorAlert message="No forecast is available." />
        <Button variant="primary" onClick={() => run.mutate()}>
          Run forecast
        </Button>
      </section>
    )

  const data = scenario ?? forecast.data
  if (!data) return <p className="text-metal-500">Select a seller.</p>

  const alert = data.alert
  const chart = data.weeks.map((row) => ({
    ...row,
    label: `W${row.week_index}`,
    low: row.p10_closing_balance_paise,
    range: row.p90_closing_balance_paise - row.p10_closing_balance_paise,
    buffer: data.run.buffer_paise,
    forecast: showForecast ? row.expected_inflow_forecast_paise : 0,
  }))

  const coverage = (backtest.data?.coverage_by_horizon ?? {}) as Record<string, number>
  const metrics = analysis.data ?? {}

  return (
    <section aria-label="Cash forecast" className="space-y-6">
      {/* Top Header & Forecast Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">13-week cash forecast</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Monte Carlo probabilistic trajectory with verifiable business evidence inputs.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <label className="inline-flex items-center gap-2 text-xs font-semibold text-metal-700 dark:text-metal-300 bg-white dark:bg-metal-900 px-3 py-1.5 rounded-xl border border-metal-200/80 dark:border-metal-800 shadow-xs cursor-pointer hover:bg-metal-50 dark:hover:bg-metal-800 transition-colors">
            <input
              type="checkbox"
              checked={showForecast}
              onChange={(event) => {
                setShowForecast(event.target.checked)
                setScenario(null)
                void koshApi
                  .runForecast(activeSellerId!, {
                    include_forecast_sales: event.target.checked,
                    include_addon_events: data.run.include_addon_events ?? true,
                    include_customer_history: data.run.include_customer_history ?? false,
                    include_revenue_signal: data.run.include_revenue_signal ?? false,
                    n_paths: data.run.n_paths ?? 2000,
                    seed: data.run.seed ?? 42,
                  })
                  .then(() => qc.invalidateQueries({ queryKey: ['kosh', 'forecast', activeSellerId] }))
              }}
              className="rounded text-primary-600 focus:ring-primary-500"
            />
            Include forecast sales
          </label>
          <button
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold shadow-xs transition-colors ${
              drawer
                ? 'bg-primary-50 dark:bg-primary-950/50 border-primary-300 text-primary-700 dark:text-primary-300'
                : 'bg-white dark:bg-metal-900 border-metal-200/80 dark:border-metal-800 text-metal-700 dark:text-metal-300 hover:bg-metal-50 dark:hover:bg-metal-800'
            }`}
            onClick={() => setDrawer(!drawer)}
          >
            <Sliders size={13} className={drawer ? 'text-primary-600' : 'text-metal-500'} />
            What-if
          </button>
        </div>
      </div>

      {/* Model Assumption Toggles Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="card p-3.5 flex items-start gap-2.5 text-xs text-metal-700 dark:text-metal-300 cursor-pointer hover:border-primary-300 transition-colors">
          <input
            type="checkbox"
            checked={data.run.include_addon_events ?? true}
            onChange={(e) => {
              setScenario(null)
              void koshApi
                .runForecast(activeSellerId!, {
                  include_addon_events: e.target.checked,
                  include_revenue_signal: data.run.include_revenue_signal ?? false,
                  include_customer_history: data.run.include_customer_history ?? false,
                  n_paths: data.run.n_paths ?? 2000,
                  seed: data.run.seed ?? 42,
                  include_forecast_sales: data.run.include_forecast_sales ?? true,
                })
                .then(() => qc.invalidateQueries({ queryKey: ['kosh', 'forecast', activeSellerId] }))
            }}
            className="mt-0.5 rounded text-primary-600 focus:ring-primary-500"
          />
          <span className="font-medium">Include confirmed add-on cash events</span>
        </label>

        <label className="card p-3.5 flex items-start gap-2.5 text-xs text-metal-700 dark:text-metal-300 cursor-pointer hover:border-primary-300 transition-colors">
          <input
            type="checkbox"
            checked={data.run.include_customer_history ?? false}
            onChange={(e) => {
              setScenario(null)
              void koshApi
                .runForecast(activeSellerId!, {
                  include_customer_history: e.target.checked,
                  include_revenue_signal: data.run.include_revenue_signal ?? false,
                  include_addon_events: data.run.include_addon_events ?? true,
                  n_paths: data.run.n_paths ?? 2000,
                  seed: data.run.seed ?? 42,
                  include_forecast_sales: data.run.include_forecast_sales ?? true,
                })
                .then(() => qc.invalidateQueries({ queryKey: ['kosh', 'forecast', activeSellerId] }))
            }}
            className="mt-0.5 rounded text-primary-600 focus:ring-primary-500"
          />
          <span className="font-medium">Include owner-confirmed additional customer delay history</span>
        </label>

        <label className={`card p-3.5 flex items-start gap-2.5 text-xs transition-colors ${
          data.run.include_forecast_sales === false ? 'opacity-50 cursor-not-allowed text-metal-400' : 'text-metal-700 dark:text-metal-300 cursor-pointer hover:border-primary-300'
        }`}>
          <input
            type="checkbox"
            checked={data.run.include_revenue_signal ?? false}
            disabled={data.run.include_forecast_sales === false}
            onChange={(e) => {
              setScenario(null)
              void koshApi
                .runForecast(activeSellerId!, {
                  include_revenue_signal: e.target.checked,
                  include_customer_history: data.run.include_customer_history ?? false,
                  include_addon_events: data.run.include_addon_events ?? true,
                  n_paths: data.run.n_paths ?? 2000,
                  seed: data.run.seed ?? 42,
                  include_forecast_sales: true,
                })
                .then(() => qc.invalidateQueries({ queryKey: ['kosh', 'forecast', activeSellerId] }))
            }}
            className="mt-0.5 rounded text-primary-600 focus:ring-primary-500"
          />
          <span className="font-medium">Use optional explainable revenue signal instead of sampled forecast sales</span>
        </label>
      </div>

      {data.weeks.some((w) => (w.expected_inflow_revenue_paise ?? 0) > 0) && (
        <div className="flex items-center gap-2.5 p-3.5 rounded-xl bg-primary-50/70 dark:bg-primary-950/30 border border-primary-200 dark:border-primary-800 text-xs text-primary-900 dark:text-primary-200">
          <Info size={15} className="text-primary-600 shrink-0" />
          <span>Includes separately labelled revenue signal cash estimates; receipt timing remains an assumption.</span>
        </div>
      )}

      {/* Add-on cash events details */}
      <details className="card p-4 space-y-2 text-xs">
        <summary className="font-semibold text-metal-800 dark:text-metal-200 cursor-pointer hover:text-primary-600 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-3.5 rounded-full bg-primary-500 shrink-0" />
            <span>Add-on cash events (proposals excluded)</span>
          </div>
          <span className="text-metal-400 font-normal">{events.data?.items.length ?? 0} events</span>
        </summary>
        <div className="pt-2 space-y-2 divide-y divide-metal-100 dark:divide-metal-800">
          {events.data?.items.map((event) => (
            <div key={event.id} className="pt-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-metal-700 dark:text-metal-300">
                <span className="font-semibold">{event.event_type}</span> · {event.source_module} ·{' '}
                <span className="font-medium text-metal-800 dark:text-metal-200">{event.status}</span> ·{' '}
                <span className="font-bold text-metal-900 dark:text-white">{formatPaiseINR(event.amount_paise)}</span> ·{' '}
                {event.event_date} · <span className="font-mono text-metal-500">{event.evidence_ref}</span>
              </p>
              {events.data?.role === 'OWNER' && event.status === 'PROPOSED' && (
                <button
                  className="btn-secondary text-[11px] py-1 px-2.5"
                  onClick={() =>
                    void koshApi
                      .confirmCashEvent(activeSellerId!, event.id)
                      .then(() => qc.invalidateQueries({ queryKey: ['kosh'] }))
                  }
                >
                  Owner confirm cash event {event.id}
                </button>
              )}
            </div>
          ))}
          {!events.data?.items.length && (
            <p className="text-metal-400 py-1">No add-on cash events recorded.</p>
          )}
        </div>
      </details>

      {data.weeks.some((w) => (w.expected_inflow_addon_paise ?? 0) > 0 || (w.expected_outflow_addon_paise ?? 0) > 0) && (
        <p className="text-xs text-metal-600 dark:text-metal-400 px-1">Forecast includes separately labelled owner-confirmed add-on cash flows.</p>
      )}

      {/* Alert Card */}
      {alert && (
        <div
          role="alert"
          className="rounded-2xl border-l-4 border-l-amber-500 border border-amber-200/90 dark:border-amber-900/50 bg-gradient-to-r from-amber-50/90 to-amber-50/30 dark:from-amber-950/30 dark:to-transparent p-5 space-y-3 shadow-xs"
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-amber-900 dark:text-amber-200">
              <AlertTriangle size={18} className="text-amber-600 shrink-0" />
              <strong className="text-sm font-bold">
                {alert.summary ?? `Week ${alert.week_index}: ${(alert.probability * 100).toFixed(0)}% chance below buffer`}
              </strong>
            </div>
            {alert.id && (
              <button
                className="self-start sm:self-auto text-xs font-semibold text-amber-800 dark:text-amber-300 underline hover:text-amber-950"
                onClick={() => koshApi.acknowledgeAlert(activeSellerId!, alert.id!)}
              >
                Acknowledge
              </button>
            )}
          </div>

          <div className="flex flex-wrap items-baseline gap-4 text-xs">
            <p className="text-amber-950 dark:text-amber-200">
              Expected shortfall <strong className="text-sm font-bold text-rose-700 dark:text-rose-400">{formatPaiseINR(alert.expected_shortfall_paise)}</strong>
            </p>
            <a
              href="/plan"
              className="inline-flex items-center gap-1 text-xs font-bold text-primary-700 dark:text-primary-300 underline hover:text-primary-900"
            >
              Build a gap-closing plan
              <ArrowRight size={12} />
            </a>
          </div>

          <div className="space-y-1.5 pt-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-amber-800/80 dark:text-amber-400">
              Contributing Causes
            </span>
            <ol className="list-decimal pl-5 text-xs text-amber-900 dark:text-amber-300 space-y-1">
              {alert.causes.map((cause, index) => (
                <li key={index}>
                  <strong>{cause.customer ?? cause.type}</strong>: {formatPaiseINR(cause.amount_paise)} (
                  {formatPaiseINR(cause.contribution_paise)} contribution)
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {data.weeks.some((w) => (w.expected_inflow_sandbox_paise ?? 0) > 0 || (w.expected_outflow_sandbox_paise ?? 0) > 0) && (
        <div className="rounded-xl border border-orange-300 dark:border-orange-800 bg-orange-50/80 dark:bg-orange-950/30 p-3 text-xs text-orange-950 dark:text-orange-200 flex items-center gap-2">
          <Shield size={14} className="text-orange-600 shrink-0" />
          <span>Includes separately labelled sandbox cash events. These are simulated entries, not real bank transactions.</span>
        </div>
      )}

      {data.under_review_paise > 0 && (
        <a
          href="/ledger"
          className="flex items-center justify-between rounded-xl bg-amber-50/90 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-900/50 p-3.5 text-xs text-amber-900 dark:text-amber-200 underline hover:bg-amber-100 transition-colors font-semibold"
        >
          <span>Under review: {formatPaiseINR(data.under_review_paise)} excluded</span>
          <ArrowRight size={14} className="no-underline text-amber-700 dark:text-amber-400" />
        </a>
      )}

      {/* Main 13-Week Chart */}
      <Card noPadding className="p-5 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Closing Balance Trajectory (P10 - P50 - P90)</h3>
          </div>
          <div className="flex items-center gap-3.5 text-xs text-metal-500 dark:text-metal-400">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-xs bg-primary-200 dark:bg-primary-800 inline-block border border-primary-400" />
              P10-P90 Range
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-primary-600 dark:bg-primary-400 inline-block" />
              P50 Median
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-rose-600 inline-block border-b border-dashed" />
              Safety Buffer
            </span>
          </div>
        </div>

        <div className="h-80 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chart} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5eaef" opacity={0.6} />
              <XAxis dataKey="label" stroke="#6b7c93" fontSize={11} />
              <YAxis tickFormatter={lakh} stroke="#6b7c93" fontSize={11} />
              <Tooltip
                formatter={(value) => [formatPaiseINR(Number(value))]}
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderRadius: '0.75rem',
                  border: '1px solid #e5eaef',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.08)',
                  fontSize: '12px',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }} />
              <Area dataKey="low" stackId="band" stroke="none" fill="transparent" />
              <Area name="P10-P90" dataKey="range" stackId="band" stroke="#6ee7b7" fill="#d1fae5" fillOpacity={0.6} />
              <Line name="P50" dataKey="p50_closing_balance_paise" stroke="#059669" strokeWidth={2.5} dot={{ r: 2 }} />
              <Line name="Buffer" dataKey="buffer" stroke="#dc2626" strokeWidth={2} strokeDasharray="5 5" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* What-If Drawer */}
      {drawer && (
        <div className="card p-5 space-y-4 border-primary-200 dark:border-primary-800 bg-primary-50/30 dark:bg-primary-950/20 animate-in fade-in duration-150">
          <div className="flex items-center justify-between border-b border-primary-100 dark:border-primary-900 pb-3">
            <div className="flex items-center gap-2">
              <Sliders size={16} className="text-primary-600" />
              <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">What-if scenario</h3>
            </div>
            <button
              onClick={() => {
                setShift(0)
                setScenario(null)
              }}
              className="inline-flex items-center gap-1 text-xs text-metal-500 hover:text-metal-800 dark:hover:text-metal-200"
            >
              <RotateCcw size={12} />
              Reset scenario
            </button>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <label className="flex-1 flex items-center gap-3 text-xs font-semibold text-metal-700 dark:text-metal-300">
              <span className="shrink-0">Customer delay shift</span>
              <input
                aria-label="Customer delay shift"
                type="range"
                min={-30}
                max={30}
                value={shift}
                onChange={(event) => setShift(Number(event.target.value))}
                className="w-full accent-primary-600"
              />
              <span className="font-bold text-sm text-primary-700 dark:text-primary-300 w-16 text-right shrink-0">
                {shift > 0 ? `+${shift}` : shift} days
              </span>
            </label>

            <button
              className="btn-primary text-xs py-1.5 px-4 self-end sm:self-auto"
              onClick={() =>
                koshApi
                  .whatIf(activeSellerId!, {
                    customer_delay_shift_days: Object.fromEntries(
                      (alert?.causes ?? []).filter((c) => c.counterparty_id).map((c) => [c.counterparty_id, shift])
                    ),
                    exclude_counterparties: [],
                    extra_inflows: [],
                  })
                  .then(setScenario)
              }
            >
              Apply
            </button>
          </div>
        </div>
      )}

      {/* Analytics & Business KPIs */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="space-y-2">
          <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-2.5">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Back-test</h3>
          </div>
          {Object.keys(coverage).length ? (
            <div className="space-y-2 pt-1 text-xs text-metal-700 dark:text-metal-300">
              <p>
                <strong>P10-P90 coverage:</strong>{' '}
                {Object.entries(coverage)
                  .map(([key, value]) => `H${key} ${(value * 100).toFixed(0)}%`)
                  .join(', ')}
              </p>
              <p className="text-[11px] text-metal-500">
                Validates empirical hit rate of confidence bands across historical forecast runs.
              </p>
            </div>
          ) : (
            <p className="text-xs text-metal-400 py-2">No back-test yet.</p>
          )}
        </Card>

        <Card className="space-y-2">
          <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-2.5">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Business analysis</h3>
          </div>
          <div className="space-y-1.5 pt-1 text-xs text-metal-700 dark:text-metal-300">
            <p>
              DSO <strong>{String(metrics.dso_days ?? '-')}</strong> days - DPO{' '}
              <strong>{String(metrics.dpo_days ?? '-')}</strong> days - CCC{' '}
              <strong>{String(metrics.cash_conversion_cycle_days ?? '-')}</strong> days
            </p>
            <p>
              Top 3 customer share:{' '}
              <strong>
                {metrics.top_3_customer_share == null ? '-' : `${(Number(metrics.top_3_customer_share) * 100).toFixed(0)}%`}
              </strong>
            </p>
          </div>
        </Card>
      </div>
    </section>
  )
}
