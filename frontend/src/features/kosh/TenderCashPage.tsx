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
import { formatPaiseINR, parseRupeesToPaise } from '@/lib/formatMoney'
import { ErrorAlert } from '@/components/ui/ErrorAlert'

interface MilestonePair {
  title: string
  phase: string
  badge: string
  cost: {
    key: string
    label: string
    placeholder: string
    description: string
  }
  date: {
    key: string
    label: string
    description: string
  }
}

const milestonePairs: MilestonePair[] = [
  {
    title: 'Earnest Money Deposit (EMD)',
    phase: 'Pre-Bid Security',
    badge: '1',
    cost: {
      key: 'emd_paise',
      label: 'EMD Cash Deposit (₹)',
      placeholder: 'e.g. 50,000 (enter 0 if exempt)',
      description: 'Documented initial tender security amount before bid submission',
    },
    date: {
      key: 'emd_date',
      label: 'EMD Submission Date',
      description: 'Date earnest deposit is debited / submitted',
    },
  },
  {
    title: 'Performance Security / Guarantee',
    phase: 'Contract Award',
    badge: '2',
    cost: {
      key: 'performance_security_cash_paise',
      label: 'Performance Security Cash Deposit (₹)',
      placeholder: 'e.g. 1,00,000 (enter 0 if BG margin only)',
      description: 'Bank guarantee margin or cash security deposit upon contract award',
    },
    date: {
      key: 'security_date',
      label: 'Security Issuance Date',
      description: 'Date performance guarantee is executed',
    },
  },
  {
    title: 'Production & Fulfillment Outlay',
    phase: 'Manufacturing & Fulfillment',
    badge: '3',
    cost: {
      key: 'production_cost_paise',
      label: 'Production & Direct Outlay (₹)',
      placeholder: 'e.g. 8,50,000',
      description: 'Direct procurement, raw materials, manufacturing and delivery expenses',
    },
    date: {
      key: 'production_date',
      label: 'Production Start Date',
      description: 'Date capital deployment begins for fulfillment',
    },
  },
  {
    title: 'Expected Contract Receipt',
    phase: 'CRAC Acceptance & Billing',
    badge: '4',
    cost: {
      key: 'contract_receivable_paise',
      label: 'Expected Contract Receipt (₹)',
      placeholder: 'e.g. 12,00,000',
      description: 'Net billing amount receivable upon Consignee Receipt (CRAC)',
    },
    date: {
      key: 'government_payment_date',
      label: 'Expected Payment Date',
      description: 'Anticipated statutory payment date (45-day statutory MSMED terms for CPSEs)',
    },
  },
  {
    title: 'EMD Refund / Release',
    phase: 'Post-Award Release',
    badge: '5',
    cost: {
      key: 'emd_refund_paise',
      label: 'Documented EMD Refund (₹)',
      placeholder: 'e.g. 50,000 (enter 0 if non-refundable/none)',
      description: 'Released earnest deposit after contract finalization or award release',
    },
    date: {
      key: 'emd_refund_date',
      label: 'Expected Refund Date',
      description: 'Expected date of EMD return credit',
    },
  },
]

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

  // Track field presence and exact integer paise parsing (preserves null vs explicit 0)
  const getMilestoneState = (costKey: string, dateKey: string) => {
    const rawCost = values[costKey]
    const isEntered = rawCost !== undefined && rawCost.trim() !== ''
    const parsedPaise = isEntered ? parseRupeesToPaise(rawCost) : null
    const isExplicitZero = isEntered && parsedPaise === 0
    const rawDate = values[dateKey]?.trim()
    const hasDate = Boolean(rawDate)
    const isCostValid = !isEntered || parsedPaise !== null
    // If explicit zero, no date is required because 0 paise creates no cashflow event
    const isDateRequired = parsedPaise !== null && parsedPaise > 0
    const isComplete = isEntered && isCostValid && (!isDateRequired || hasDate)

    return {
      rawCost,
      isEntered,
      parsedPaise,
      isExplicitZero,
      isCostValid,
      rawDate,
      hasDate,
      isDateRequired,
      isComplete,
    }
  }

  const emdState = getMilestoneState('emd_paise', 'emd_date')
  const securityState = getMilestoneState('performance_security_cash_paise', 'security_date')
  const productionState = getMilestoneState('production_cost_paise', 'production_date')
  const contractState = getMilestoneState('contract_receivable_paise', 'government_payment_date')
  const refundState = getMilestoneState('emd_refund_paise', 'emd_refund_date')

  const milestoneStates = [
    { key: 'emd_paise', label: 'Earnest Money Deposit (EMD)', state: emdState, isOutlay: true },
    { key: 'performance_security_cash_paise', label: 'Performance Security', state: securityState, isOutlay: true },
    { key: 'production_cost_paise', label: 'Production Cost', state: productionState, isOutlay: true },
    { key: 'contract_receivable_paise', label: 'Contract Receivable', state: contractState, isOutlay: false },
    { key: 'emd_refund_paise', label: 'EMD Refund / Release', state: refundState, isOutlay: false },
  ]

  // Count entered fields vs missing (preserves distinction between explicit 0 and omitted null)
  const enteredOutlays = [emdState, securityState, productionState].filter((s) => s.isEntered && s.parsedPaise !== null)
  const enteredInflows = [contractState, refundState].filter((s) => s.isEntered && s.parsedPaise !== null)
  const unenteredOutlayCount = 3 - enteredOutlays.length
  const unenteredInflowCount = 2 - enteredInflows.length

  const totalEnteredOutlayPaise = enteredOutlays.reduce((acc, s) => acc + (s.parsedPaise ?? 0), 0)
  const totalEnteredInflowPaise = enteredInflows.reduce((acc, s) => acc + (s.parsedPaise ?? 0), 0)

  const hasAnyInput = Object.values(values).some((v) => v !== undefined && v.trim() !== '') || Boolean(selected) || Boolean(evidence.trim()) || cpse !== ''
  const allMilestonesComplete = milestoneStates.every((m) => m.state.isComplete)
  const hasCpseStatus = cpse !== ''
  const hasEvidence = Boolean(evidence.trim())
  const hasTender = Boolean(selected)
  const isScenarioFullySpecified = hasTender && hasEvidence && hasCpseStatus && allMilestonesComplete

  // Missing fields list for user guidance
  const missingInputs: string[] = []
  if (!hasTender) missingInputs.push('Matched tender selection')
  if (!hasEvidence) missingInputs.push('Evidence reference')
  if (!hasCpseStatus) missingInputs.push('Documented CPSE buyer classification (Pending review)')
  for (const m of milestoneStates) {
    if (!m.state.isEntered) {
      missingInputs.push(`${m.label} amount`)
    } else if (m.state.parsedPaise === null) {
      missingInputs.push(`${m.label} valid number`)
    } else if (m.state.isDateRequired && !m.state.hasDate) {
      missingInputs.push(`${m.label} date`)
    }
  }

  // Dated Interim Liquidity Timeline Calculation (mirrors backend exact logic)
  const datedEvents: {
    key: string
    label: string
    date: string
    amountPaise: number
    isOutlay: boolean
  }[] = []

  if (emdState.parsedPaise !== null && emdState.parsedPaise > 0 && emdState.rawDate) {
    datedEvents.push({ key: 'emd', label: 'EMD Outlay', date: emdState.rawDate, amountPaise: -emdState.parsedPaise, isOutlay: true })
  }
  if (securityState.parsedPaise !== null && securityState.parsedPaise > 0 && securityState.rawDate) {
    datedEvents.push({ key: 'security', label: 'Performance Security Deposit', date: securityState.rawDate, amountPaise: -securityState.parsedPaise, isOutlay: true })
  }
  if (productionState.parsedPaise !== null && productionState.parsedPaise > 0 && productionState.rawDate) {
    datedEvents.push({ key: 'production', label: 'Production / Fulfillment Outlay', date: productionState.rawDate, amountPaise: -productionState.parsedPaise, isOutlay: true })
  }
  if (contractState.parsedPaise !== null && contractState.parsedPaise > 0 && contractState.rawDate) {
    datedEvents.push({ key: 'contract', label: 'CRAC Acceptance & Billing Inflow', date: contractState.rawDate, amountPaise: contractState.parsedPaise, isOutlay: false })
  }
  if (refundState.parsedPaise !== null && refundState.parsedPaise > 0 && refundState.rawDate) {
    datedEvents.push({ key: 'refund', label: 'EMD Release / Refund Credit', date: refundState.rawDate, amountPaise: refundState.parsedPaise, isOutlay: false })
  }

  // Sort events chronologically by date
  datedEvents.sort((a, b) => a.date.localeCompare(b.date) || a.amountPaise - b.amountPaise)

  let cumulativePaise = 0
  let peakWorkingCapitalNeededPaise = 0
  const datedSchedule = datedEvents.map((evt) => {
    cumulativePaise += evt.amountPaise
    if (-cumulativePaise > peakWorkingCapitalNeededPaise) {
      peakWorkingCapitalNeededPaise = -cumulativePaise
    }
    return {
      ...evt,
      runningBalancePaise: cumulativePaise,
    }
  })

  const submit = async () => {
    setLoading(true)
    const payload: Record<string, unknown> = {
      evidence_ref: evidence,
      cpse_buyer: cpse === '' ? null : cpse === 'true',
    }
    for (const pair of milestonePairs) {
      payload[pair.cost.key] = parseRupeesToPaise(values[pair.cost.key])
      payload[pair.date.key] = values[pair.date.key]?.trim() ? values[pair.date.key].trim() : null
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
          <div className="mt-2 text-[11px] text-muted-foreground bg-muted/30 px-3 py-1.5 rounded-lg border border-border/50 inline-flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span>Fictional demonstration data · Simulated local scenario only · No real banking execution, tender award, or credit sanction.</span>
          </div>
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
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-8 items-start">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
          className="space-y-6"
        >
          {/* Step 1: Tender Selection & Counterparty Verification */}
          <div className="card space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-metal-100 dark:border-metal-800">
              <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
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
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                >
                  <option value="">Select a matched GeM tender</option>
                  {query.data?.items?.map((t) => (
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
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
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
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
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
                    Enter documented amounts in Rupees (₹) and milestone dates. Values convert exactly to integer paise with zero floating-point imprecision.
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              {milestonePairs.map((pair) => (
                <div
                  key={pair.title}
                  className="p-4 rounded-xl border border-border bg-card shadow-2xs space-y-3"
                >
                  <div className="flex items-center justify-between pb-2 border-b border-border/50">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-primary-100 dark:bg-primary-950/60 text-primary-800 dark:text-primary-300 border border-primary-200 dark:border-primary-800 text-[11px] font-bold flex items-center justify-center shrink-0">
                        {pair.badge}
                      </span>
                      <h4 className="text-xs font-bold text-foreground">{pair.title}</h4>
                    </div>
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider bg-muted/40 px-2 py-0.5 rounded">
                      {pair.phase}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        {pair.cost.label}
                      </label>
                      <div className="relative">
                        <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-muted-foreground font-semibold text-xs">
                          ₹
                        </span>
                        <input
                          type="text"
                          inputMode="decimal"
                          placeholder={pair.cost.placeholder}
                          value={values[pair.cost.key] ?? ''}
                          onChange={(e) =>
                            setValues((prev) => ({ ...prev, [pair.cost.key]: e.target.value }))
                          }
                          className="w-full pl-7 pr-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors font-mono"
                        />
                      </div>
                      <div className="flex items-center justify-between mt-1 text-[11px]">
                        <span className="text-muted-foreground">{pair.cost.description}</span>
                        {values[pair.cost.key] && parseRupeesToPaise(values[pair.cost.key]) !== null && (
                          <span className="font-mono font-semibold text-emerald-700 dark:text-emerald-400">
                            ≈ {formatPaiseINR(parseRupeesToPaise(values[pair.cost.key]))}
                          </span>
                        )}
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        {pair.date.label}
                      </label>
                      <input
                        type="date"
                        value={values[pair.date.key] ?? ''}
                        onChange={(e) =>
                          setValues((prev) => ({ ...prev, [pair.date.key]: e.target.value }))
                        }
                        className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                      />
                      <span className="text-[11px] text-muted-foreground mt-1 block">
                        {pair.date.description}
                      </span>
                    </div>
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
              <Sparkles className="w-4 h-4 text-primary-600" />
              {loading ? 'Simulating cash impact...' : 'Run same-seed tender scenario'}
            </button>
          </div>
        </form>

        {/* Right Column: Live Summary & Financing Context */}
        <div className="space-y-6">
          {/* Live Order Scenario Summary Card */}
          <div className="card space-y-4 border-primary-200 dark:border-primary-800/60 bg-gradient-to-br from-card via-card to-primary-500/5 shadow-sm">
            <div className="flex items-center justify-between pb-2 border-b border-border">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">
                  Order Cash Projection
                </h4>
              </div>
              <span className="text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-950/60 px-2 py-0.5 rounded-full border border-emerald-300 dark:border-emerald-700">
                Live Preview
              </span>
            </div>

            {!hasAnyInput ? (
              <div className="space-y-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Total Cash Outlay:</span>
                  <span className="font-mono text-muted-foreground italic">
                    Not entered (3 pending)
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Expected Inflow:</span>
                  <span className="font-mono text-muted-foreground italic">
                    Not entered (2 pending)
                  </span>
                </div>
                <div className="pt-2 border-t border-border/60 flex items-center justify-between">
                  <span className="font-semibold text-foreground">
                    Scenario Completeness:
                  </span>
                  <span className="text-xs font-semibold text-metal-600 dark:text-metal-400 bg-metal-100 dark:bg-metal-800 px-2.5 py-1 rounded-md">
                    No inputs entered
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground bg-muted/40 p-2 rounded border border-border/50">
                  Select a tender, provide audit evidence, and enter milestone costs and dates. Explicit 0 is preserved for MSME exemptions.
                </p>
              </div>
            ) : (
              <div className="space-y-3 text-xs">
                {/* Outlay Row */}
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-muted-foreground">Total Cash Outlay:</span>
                    {unenteredOutlayCount > 0 ? (
                      <span className="text-[10px] text-amber-600 dark:text-amber-400">
                        {unenteredOutlayCount} of 3 outlays pending
                      </span>
                    ) : enteredOutlays.some((s) => s.isExplicitZero) ? (
                      <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
                        Includes valid explicit ₹0.00
                      </span>
                    ) : null}
                  </div>
                  <span className="font-mono font-bold text-foreground">
                    {enteredOutlays.length > 0 ? formatPaiseINR(totalEnteredOutlayPaise) : 'Not entered'}
                  </span>
                </div>

                {/* Inflow Row */}
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-muted-foreground">Expected Inflow:</span>
                    {unenteredInflowCount > 0 ? (
                      <span className="text-[10px] text-amber-600 dark:text-amber-400">
                        {unenteredInflowCount} of 2 inflows pending
                      </span>
                    ) : enteredInflows.some((s) => s.isExplicitZero) ? (
                      <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
                        Includes valid explicit ₹0.00
                      </span>
                    ) : null}
                  </div>
                  <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400">
                    {enteredInflows.length > 0 ? formatPaiseINR(totalEnteredInflowPaise) : 'Not entered'}
                  </span>
                </div>

                {/* Nominal Surplus / Deficit */}
                {(enteredOutlays.length > 0 || enteredInflows.length > 0) && (
                  <div className="pt-2 border-t border-border/60 flex items-center justify-between">
                    <span className="font-semibold text-foreground">
                      {totalEnteredInflowPaise >= totalEnteredOutlayPaise ? 'Nominal Order Surplus:' : 'Nominal Order Deficit:'}
                    </span>
                    <span className={`font-mono font-bold text-sm ${totalEnteredInflowPaise >= totalEnteredOutlayPaise ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}>
                      {totalEnteredInflowPaise >= totalEnteredOutlayPaise
                        ? `+${formatPaiseINR(totalEnteredInflowPaise - totalEnteredOutlayPaise)}`
                        : `-${formatPaiseINR(totalEnteredOutlayPaise - totalEnteredInflowPaise)}`}
                    </span>
                  </div>
                )}

                {/* Dated Interim Liquidity Section */}
                {datedEvents.length > 0 && (
                  <div className="pt-3 border-t border-border/60 space-y-2.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 font-semibold text-foreground">
                        <Clock className="w-3.5 h-3.5 text-primary-600" />
                        <span>Peak Interim Working Capital Drag:</span>
                      </div>
                      <span className="font-mono font-bold text-sm text-amber-700 dark:text-amber-400">
                        {formatPaiseINR(peakWorkingCapitalNeededPaise)}
                      </span>
                    </div>

                    <div className="p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/60 text-[11px] text-amber-900 dark:text-amber-200 space-y-1">
                      <div className="flex items-center gap-1.5 font-semibold text-amber-800 dark:text-amber-300">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                        <span>Gross Order Cash Required Before Receipts</span>
                      </div>
                      <p className="leading-snug text-amber-800 dark:text-amber-300">
                        Gross interim outlay of {formatPaiseINR(peakWorkingCapitalNeededPaise)} occurs during manufacturing before billing receipts clear. This gross requirement alone does not mean financing is needed; feasibility is evaluated against available bank liquidity and existing commitments.
                      </p>
                    </div>

                    {/* Dated Schedule Mini-timeline */}
                    <div className="mt-2 space-y-1 border border-border/60 rounded-lg p-2 bg-muted/20">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground block mb-1">
                        Dated Liquidity Path ({datedSchedule.length} events)
                      </span>
                      {datedSchedule.map((evt, idx) => (
                        <div key={idx} className="flex items-center justify-between text-[11px] py-0.5 border-b border-border/30 last:border-0">
                          <span className="font-mono text-muted-foreground">{evt.date}</span>
                          <span className="truncate max-w-[120px] text-foreground">{evt.label}</span>
                          <span className={`font-mono font-semibold ${evt.isOutlay ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                            {evt.amountPaise < 0 ? `-${formatPaiseINR(-evt.amountPaise)}` : `+${formatPaiseINR(evt.amountPaise)}`}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Scenario Completeness Status */}
                <div className="pt-2 border-t border-border/60 flex items-center justify-between">
                  <span className="font-semibold text-foreground">Scenario Completeness:</span>
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${
                    isScenarioFullySpecified
                      ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700'
                      : 'bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-700'
                  }`}>
                    {isScenarioFullySpecified ? 'Fully Validated' : `${missingInputs.length} Pending Facts`}
                  </span>
                </div>

                {!isScenarioFullySpecified && (
                  <div className="p-2 rounded bg-muted/40 text-[11px] text-muted-foreground space-y-1">
                    <span className="font-semibold text-foreground block">Pending validation:</span>
                    <ul className="list-disc pl-4 space-y-0.5">
                      {missingInputs.map((item, idx) => (
                        <li key={idx}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <div className="p-2.5 rounded-lg bg-muted/40 border border-border text-[11px] space-y-1">
              <span className="font-semibold text-foreground block">Procurement Channel Terms:</span>
              <p className="text-muted-foreground">
                {cpse === 'true'
                  ? 'CPSE / Central Govt buyer confirmed: eligible for TReDS invoice discounting & statutory 45-day MSMED clause.'
                  : cpse === 'false'
                  ? 'Other Govt entity: non-CPSE terms apply; bank guarantee & standard payment cycles modeled.'
                  : 'CPSE status unconfirmed: submit documented buyer evidence to evaluate invoice discounting.'}
              </p>
            </div>
          </div>

          <div className="card space-y-3 bg-muted/20 border-border">
            <div className="flex items-center gap-2 text-foreground font-semibold text-xs tracking-wider uppercase">
              <Info className="w-4 h-4 text-primary-600" />
              How Tender Cash Feasibility Works
            </div>
            <ul className="text-xs text-muted-foreground space-y-2.5 leading-relaxed">
              <li className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 mt-1.5 shrink-0" />
                <span>
                  <strong>Strict Pre-Award Isolation:</strong> Running this simulation calculates cash
                  drag without placing real orders, reserving balances or notifying buyers.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 mt-1.5 shrink-0" />
                <span>
                  <strong>Gross Outlay vs. Financing Gap:</strong> Peak interim outlay represents gross order cash required before receipts. It does not by itself prove external financing is needed; the backend simulates the order atop available liquidity and existing obligations to test whether the safety buffer remains protected.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 mt-1.5 shrink-0" />
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
                    Gross Order Cash Required Before Receipts
                  </span>
                  <p className="text-lg font-bold font-mono text-foreground mt-0.5">
                    {formatPaiseINR(result.working_capital_needed_paise)}
                  </p>
                  <span className="text-[11px] text-muted-foreground block mt-0.5">
                    Tested against available bank liquidity & safety buffer
                  </span>
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
                <Layers className="w-4 h-4 text-primary-600" />
                Financing Suggestions & Eligibility
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {result.financing_suggestions.map((s) => (
                  <div
                    key={s.product}
                    className="card p-4 space-y-2 border-border bg-card hover:border-primary-300 dark:hover:border-primary-700 transition-colors"
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
