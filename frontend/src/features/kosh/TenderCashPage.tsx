import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, Link } from 'react-router-dom'
import {
  Calculator,
  ShieldCheck,
  AlertCircle,
  FileCheck,
  ArrowRight,
  Sparkles,
  TrendingUp,
  Clock,
  Layers,
  Info,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
import { ErrorAlert } from '@/components/ui/ErrorAlert'

interface FieldDef {
  key: string
  label: string
  type: 'number' | 'date'
  step?: string
  description?: string
}

const fieldPairs: { title: string; cost: FieldDef; date: FieldDef }[] = [
  {
    title: '1. Earnest Money Deposit (EMD)',
    cost: {
      key: 'emd_paise',
      label: 'EMD cash requirement (paise)',
      type: 'number',
      description: 'Documented initial tender security amount',
    },
    date: {
      key: 'emd_date',
      label: 'EMD date',
      type: 'date',
      description: 'Submission date',
    },
  },
  {
    title: '2. Performance Security / Guarantee',
    cost: {
      key: 'performance_security_cash_paise',
      label: 'Performance security cash cost / deposit (paise)',
      type: 'number',
      description: 'Bank guarantee margin or cash deposit upon award',
    },
    date: {
      key: 'security_date',
      label: 'Security date',
      type: 'date',
      description: 'Issuance date',
    },
  },
  {
    title: '3. Production & Fulfillment Outlay',
    cost: {
      key: 'production_cost_paise',
      label: 'Production cost before payment (paise)',
      type: 'number',
      description: 'Direct procurement, manufacturing and delivery cost',
    },
    date: {
      key: 'production_date',
      label: 'Production date',
      type: 'date',
      description: 'Manufacturing start',
    },
  },
  {
    title: '4. Expected Contract Receipt',
    cost: {
      key: 'contract_receivable_paise',
      label: 'Expected contract receipt (paise)',
      type: 'number',
      description: 'Net billing value receivable upon delivery / CRAC',
    },
    date: {
      key: 'government_payment_date',
      label: 'Government payment date',
      type: 'date',
      description: 'Anticipated receipt',
    },
  },
  {
    title: '5. EMD Refund / Release',
    cost: {
      key: 'emd_refund_paise',
      label: 'Documented EMD refund (paise; zero if none)',
      type: 'number',
      description: 'Released earnest deposit after contract finalization',
    },
    date: {
      key: 'emd_refund_date',
      label: 'Refund date',
      type: 'date',
      description: 'Expected return',
    },
  },
]

// Flat list for programmatic iterations
const fields = fieldPairs.flatMap((p) => [
  [p.cost.key, p.cost.label, p.cost.type] as [string, string, string],
  [p.date.key, p.date.label, p.date.type] as [string, string, string],
])

export const TenderCashPage = () => {
  const { activeSellerId } = useSeller()
  const { tenderId } = useParams()
  const [selected, setSelected] = useState(tenderId ?? '')
  const [values, setValues] = useState<Record<string, string>>({})
  const [cpse, setCpse] = useState('')
  const [evidence, setEvidence] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<Awaited<ReturnType<typeof koshApi.tenderCash>> | null>(null)

  const query = useQuery({
    queryKey: ['kosh', 'tender-cash', activeSellerId],
    queryFn: () => koshApi.tenderCashList(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const submit = async () => {
    setLoading(true)
    const payload: Record<string, unknown> = {
      evidence_ref: evidence,
      cpse_buyer: cpse === '' ? null : cpse === 'true',
    }
    for (const [key, , type] of fields) {
      payload[key] = values[key]
        ? type === 'number'
          ? Number(values[key])
          : values[key]
        : null
    }

    try {
      const res = await koshApi.tenderCash(activeSellerId!, Number(selected), payload)
      setResult(res)
      setError('')
    } catch (err) {
      const e = err as { response?: { data?: { detail?: unknown } } }
      setError(JSON.stringify(e.response?.data?.detail ?? String(err)))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section aria-label="Tender to cash" className="space-y-8 animate-fadeIn">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-border">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 mb-2">
            <Calculator className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
            Working Capital Pre-Flight Simulator
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">
            Can I afford this order?
          </h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Matched-tender cash scenario. Enter documented costs and dates; unknown inputs remain in
            review. This does not award the tender or execute funding.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to="/plan"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            Financing criteria
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <Link
            to="/cash"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            Cash loop
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>

      {/* Main Simulation Form */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
          className="lg:col-span-2 space-y-6"
        >
          {/* Step 1: Tender Selection & Counterparty Verification */}
          <div className="card space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-border">
              <div className="p-1.5 rounded-md bg-brand-navy/10 text-brand-navy dark:bg-brand-gold/10 dark:text-brand-gold">
                <FileCheck className="w-4 h-4" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">
                Tender Target & Counterparty Context
              </h3>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Matched tender <span className="text-rose-600">*</span>
                </label>
                <select
                  required
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                >
                  <option value="">Select a matched GeM tender</option>
                  {query.data?.items.map((t) => (
                    <option key={t.tender_id} value={t.tender_id}>
                      {t.bid_number} · {t.title}
                    </option>
                  ))}
                </select>
                <span className="text-[11px] text-muted-foreground mt-1 block">
                  Select an active tender opportunity discovered from your GeM matches
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Documented CPSE buyer
                  </label>
                  <select
                    value={cpse}
                    onChange={(e) => setCpse(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                  >
                    <option value="">Unknown / Pending review</option>
                    <option value="true">Yes, evidence supplied (CPSE / Central Dept)</option>
                    <option value="false">No, evidence supplied (Other Govt entity)</option>
                  </select>
                  <span className="text-[11px] text-muted-foreground mt-1 block">
                    Public sector enterprises follow standard TReDS & 45-day statutory MSMED terms
                  </span>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Evidence reference <span className="text-rose-600">*</span>
                  </label>
                  <input
                    required
                    placeholder="e.g. GeM-BID-2026-DOC-01, Clause 14"
                    value={evidence}
                    onChange={(e) => setEvidence(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                  />
                  <span className="text-[11px] text-muted-foreground mt-1 block">
                    Audit trail reference verifying milestone schedules and values
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Step 2: Milestone Schedule Outlays & Dates */}
          <div className="card space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400">
                  <Clock className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-foreground">
                    Cashflow Milestone Timeline & Amounts
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    Enter documented amounts in integer paise (1 Rupee = 100 paise) and milestone dates.
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-4 divide-y divide-border/60">
              {fieldPairs.map((pair, idx) => (
                <div
                  key={pair.title}
                  className={`grid grid-cols-1 sm:grid-cols-2 gap-4 ${idx > 0 ? 'pt-4' : ''}`}
                >
                  <div className="col-span-full">
                    <span className="text-xs font-bold text-foreground tracking-wide flex items-center gap-1.5">
                      {pair.title}
                    </span>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-foreground mb-1">
                      {pair.cost.label}
                    </label>
                    <input
                      type={pair.cost.type}
                      min="0"
                      step="1"
                      placeholder="0"
                      value={values[pair.cost.key] ?? ''}
                      onChange={(e) =>
                        setValues({ ...values, [pair.cost.key]: e.target.value })
                      }
                      className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                    />
                    {values[pair.cost.key] && !isNaN(Number(values[pair.cost.key])) && (
                      <span className="text-[11px] font-mono text-emerald-700 dark:text-emerald-400 mt-0.5 block">
                        ≈ {formatPaiseINR(Number(values[pair.cost.key]))}
                      </span>
                    )}
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-foreground mb-1">
                      {pair.date.label}
                    </label>
                    <input
                      type={pair.date.type}
                      value={values[pair.date.key] ?? ''}
                      onChange={(e) =>
                        setValues({ ...values, [pair.date.key]: e.target.value })
                      }
                      className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                    />
                    <span className="text-[11px] text-muted-foreground mt-0.5 block">
                      {pair.date.description}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Action Row */}
          <div className="flex items-center justify-between pt-2">
            <span className="text-xs text-muted-foreground">
              Simulation is deterministic and runs locally with Monte Carlo path modeling.
            </span>
            <button
              type="submit"
              disabled={loading || !selected || !evidence}
              className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold shadow-sm disabled:opacity-50"
            >
              <Sparkles className="w-4 h-4 text-brand-gold" />
              {loading ? 'Simulating cash impact...' : 'Run same-seed tender scenario'}
            </button>
          </div>
        </form>

        {/* Right Column: Educational Context & Pre-Flight Notes */}
        <div className="space-y-6">
          <div className="card space-y-3 bg-muted/20 border-border">
            <div className="flex items-center gap-2 text-foreground font-semibold text-xs tracking-wider uppercase">
              <Info className="w-4 h-4 text-brand-gold" />
              How Tender Cash Feasibility Works
            </div>
            <ul className="text-xs text-muted-foreground space-y-2.5 leading-relaxed">
              <li className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-gold mt-1.5 shrink-0" />
                <span>
                  <strong>Strict Pre-Award Isolation:</strong> Running this simulation calculates cash
                  drag without placing real orders, reserving balances or notifying buyers.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-gold mt-1.5 shrink-0" />
                <span>
                  <strong>Working Capital Deficit:</strong> Shortfalls represent the maximum cumulative
                  cash outflow before milestone receipts arrive.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-gold mt-1.5 shrink-0" />
                <span>
                  <strong>Conservative Uncertainty:</strong> Unverified milestones or unevidenced dates
                  are treated as review-required and not assumed to fund your safety buffer.
                </span>
              </li>
            </ul>
          </div>

          <div className="card border-border space-y-3">
            <div className="flex items-center gap-2 text-foreground font-semibold text-xs tracking-wider uppercase">
              <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              Financing Policy Rules
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              If the scenario reveals a deficit, Kosh evaluates pre-qualification against TReDS
              (CPSE/corporate buyers only), PO financing (minimum 24-month track record), and NBFC lines.
            </p>
          </div>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="mt-4">
          <p role="alert" className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-sm">
            {error}
          </p>
        </div>
      )}

      {/* Results Section */}
      {result && (
        <div className="mt-8 space-y-6 pt-6 border-t border-border animate-fadeIn">
          {/* Result Status Header */}
          <div className="card bg-card border-border space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <span className="text-xs uppercase tracking-wider font-semibold text-muted-foreground">
                  Simulation Outcome
                </span>
                <p role="status" className="text-xl font-bold text-foreground mt-0.5">
                  {result.status} · {result.safety}
                </p>
              </div>

              {result.working_capital_needed_paise != null && (
                <div className="p-3 rounded-lg bg-muted/40 border border-border">
                  <span className="text-xs text-muted-foreground block">
                    Peak Order Working Capital Needed
                  </span>
                  <p className="text-lg font-bold font-mono text-foreground mt-0.5">
                    Peak order working capital: {formatPaiseINR(result.working_capital_needed_paise)}
                  </p>
                </div>
              )}
            </div>

            {/* Review Required Banners */}
            {result.missing.length > 0 && (
              <div className="p-3.5 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-900 dark:text-amber-200 text-xs">
                <p className="font-semibold mb-1 flex items-center gap-1.5">
                  <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                  Review required: {result.missing.map((m) => m.replace(/_/g, ' ')).join(', ')}
                </p>
                <p className="text-amber-800 dark:text-amber-300">
                  Some milestone fields lack documented verification. Conservative model holds these as zero until verified.
                </p>
              </div>
            )}
          </div>

          {/* Financing Suggestions */}
          {result.financing_suggestions && result.financing_suggestions.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-foreground tracking-wide flex items-center gap-2">
                <Layers className="w-4 h-4 text-brand-gold" />
                Financing Suggestions & Eligibility
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {result.financing_suggestions.map((s) => (
                  <div
                    key={s.product}
                    className="card p-4 space-y-2 border-border bg-card hover:border-brand-gold/40 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-sm text-foreground">{s.product}</span>
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                          s.status === 'ELIGIBLE' || s.status === 'MATCHED'
                            ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                            : 'bg-muted text-muted-foreground border border-border'
                        }`}
                      >
                        {s.status}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {s.product}: {s.status} · {s.reason}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Scenario Weeks Table */}
          {result.scenario_weeks && result.scenario_weeks.length > 0 && (
            <div className="card space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">
                    13-Week Cash Runway Scenario
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    Projected median closing balance and probability of falling below the minimum safe buffer.
                  </p>
                </div>
              </div>

              <div className="table-container">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/60 text-muted-foreground uppercase text-[11px] font-semibold border-b border-border">
                    <tr>
                      <th className="px-4 py-3">Week</th>
                      <th className="px-4 py-3">Scenario P50</th>
                      <th className="px-4 py-3">Below buffer</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {result.scenario_weeks.map((w) => (
                      <tr key={w.week_index} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-3 font-medium text-foreground">
                          Week {w.week_index}
                        </td>
                        <td className="px-4 py-3 font-mono font-semibold text-foreground">
                          {formatPaiseINR(w.p50_closing_balance_paise)}
                        </td>
                        <td className="px-4 py-3 font-mono">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                              w.prob_below_buffer > 0.2
                                ? 'bg-rose-50 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300'
                                : w.prob_below_buffer > 0.05
                                ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300'
                                : 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300'
                            }`}
                          >
                            {(w.prob_below_buffer * 100).toFixed(1)}% ({w.prob_below_buffer})
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Footer Navigation Links */}
      <div className="flex flex-wrap items-center gap-4 pt-6 border-t border-border text-xs text-muted-foreground">
        <Link
          to="/"
          className="hover:text-foreground hover:underline transition-colors flex items-center gap-1 font-medium"
        >
          All existing GeM tender features
        </Link>
        <span>·</span>
        <Link
          to="/cash"
          className="hover:text-foreground hover:underline transition-colors flex items-center gap-1 font-medium"
        >
          Cash
        </Link>
        <span>·</span>
        <Link
          to="/plan"
          className="hover:text-foreground hover:underline transition-colors flex items-center gap-1 font-medium"
        >
          Financing criteria
        </Link>
      </div>
    </section>
  )
}
