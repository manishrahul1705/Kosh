import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  Briefcase,
  ShoppingCart,
  TrendingDown,
  TrendingUp,
  FileText,
  Send,
  AlertCircle,
  CheckCircle2,
  Clock,
  ArrowRight,
  Sparkles,
  PackageCheck,
  ShieldAlert,
  Calculator,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { OperationResources, BusinessFields } from './OperationResources'

export const OperationsPage = () => {
  const { activeSellerId } = useSeller()
  const { module } = useParams()
  const qc = useQueryClient()

  const [message, setMessage] = useState('')
  const [party, setParty] = useState('')
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState('')
  const [material, setMaterial] = useState('')
  const [evidence, setEvidence] = useState('')
  const [po, setPo] = useState('')
  const [percent, setPercent] = useState('')
  const [estimatedCost, setEstimatedCost] = useState('')
  const [document, setDocument] = useState('')
  const [sale, setSale] = useState('')
  const [surcharge, setSurcharge] = useState<Record<string, unknown> | null>(null)
  const [quantity, setQuantity] = useState('')
  const [draft, setDraft] = useState<{ id: number; body: string } | null>(null)

  const query = useQuery({
    queryKey: ['kosh', 'operations', activeSellerId],
    queryFn: () => koshApi.operations(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const run = async (task: () => Promise<unknown>) => {
    try {
      await task()
      setMessage('Saved.')
      await qc.invalidateQueries({ queryKey: ['kosh'] })
    } catch (error) {
      const e = error as { response?: { data?: { detail?: unknown } } }
      setMessage(JSON.stringify(e.response?.data?.detail ?? String(error)))
    }
  }

  const navLinks = [
    { to: '/operations/sales', label: 'Sales intake', icon: ShoppingCart },
    { to: '/operations/procurement', label: 'Procurement / RFQs', icon: PackageCheck },
    { to: '/operations/pricing', label: 'Pricing / market', icon: TrendingDown },
    { to: '/operations/collections', label: 'Collections', icon: Clock },
    { to: '/operations/resources', label: 'Operational resources / workers', icon: Briefcase },
    { to: '/operations/customer-intelligence', label: 'Customers / what-if', icon: Sparkles },
    { to: '/operations/revenue', label: 'Revenue signal', icon: TrendingUp },
    { to: '/operations/reports', label: 'Reports', icon: FileText },
    { to: '/operations/tender-to-cash', label: 'Tender to cash', icon: Calculator },
    { to: '/cash', label: 'Cash loop', icon: ArrowRight },
    { to: '/approvals', label: 'Approvals', icon: ArrowRight },
  ]

  const activeTab = module ?? 'overview'

  return (
    <section aria-label="Operations" className="space-y-6 animate-fadeIn">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-metal-200/80 dark:border-metal-800">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold tracking-tight text-metal-900 dark:text-white">
              Operations · {activeTab}
            </h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5 max-w-3xl">
            Propose evidence-backed sales, procurement, pricing changes and operational workflows.
            Cash impact remains excluded until explicit owner confirmation.
          </p>
        </div>
      </div>

      {/* Operations Sub-Navigation Bar */}
      <nav className="flex items-center gap-1.5 overflow-x-auto pb-2 border-b border-metal-200/80 dark:border-metal-800 text-xs scrollbar-none">
        {navLinks.map((link) => {
          const isActive =
            link.to === `/operations/${module}` ||
            (link.to === '/operations/resources' && !module)
          return (
            <Link
              key={link.to}
              to={link.to}
              className={`px-3 py-1.5 rounded-xl font-semibold whitespace-nowrap transition-all flex items-center gap-1.5 ${
                isActive
                  ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-xs'
                  : 'text-metal-600 dark:text-metal-400 hover:text-metal-900 dark:hover:text-white hover:bg-metal-100 dark:hover:bg-metal-800'
              }`}
            >
              <link.icon className="w-3.5 h-3.5" />
              {link.label}
            </Link>
          )
        })}
      </nav>

      {/* Toast / Status messages */}
      {message && (
        <div className="p-3.5 rounded-xl bg-primary-50 dark:bg-primary-950/40 border border-primary-200 dark:border-primary-800 text-primary-900 dark:text-primary-200 text-xs font-semibold flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-primary-600 dark:text-primary-400 shrink-0" />
          <p role="status">{message}</p>
        </div>
      )}

      {query.isError && (
        <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-900 dark:text-rose-200 text-xs font-semibold flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
          <p role="alert">Unable to load operations.</p>
        </div>
      )}

      {/* Sales / Procurement Proposal Forms */}
      {query.data?.role !== 'VIEWER' && ['sales', 'procurement'].includes(module ?? '') && (
        <Card noPadding className="p-5 space-y-5">
          <div className="flex items-center gap-2 pb-3 border-b border-metal-100 dark:border-metal-800">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <div>
              <h3 className="text-base font-bold text-metal-900 dark:text-white tracking-tight">
                {module === 'sales' ? 'Confirmed-sales proposal' : 'Purchase-order proposal'}
              </h3>
              <p className="text-xs text-metal-500 dark:text-metal-400">
                Cash remains excluded until the owner confirms this evidence-backed proposal.
              </p>
            </div>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(() =>
                koshApi.orderProposal(activeSellerId!, {
                  direction: module === 'sales' ? 'SALE' : 'PO',
                  counterparty_id: Number(party),
                  amount_paise: Number(amount),
                  payment_date: day,
                  material_code: material,
                  evidence_ref: evidence,
                  estimated_cost_paise: estimatedCost ? Number(estimatedCost) : null,
                })
              )
            }}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Counterparty <span className="text-rose-600">*</span>
                </label>
                <select
                  required
                  value={party}
                  onChange={(e) => setParty(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                >
                  <option value="">Select counterparty</option>
                  {query.data?.counterparties?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Amount (paise) <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  type="number"
                  min="1"
                  step="1"
                  placeholder="e.g. 5000000"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                />
                {amount && !isNaN(Number(amount)) && (
                  <span className="text-[11px] font-mono text-primary-700 dark:text-primary-300 mt-1 block">
                    ≈ {formatPaiseINR(Number(amount))}
                  </span>
                )}
              </div>

              <div>
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Payment date <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  type="date"
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Material code <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  pattern="[A-Z0-9_-]{1,40}"
                  placeholder="e.g. MAT-STEEL-01"
                  value={material}
                  onChange={(e) => setMaterial(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors uppercase font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Evidence reference <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  placeholder="e.g. PO-2026-904, Signed Contract"
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Documented estimated cost (paise; optional)
                </label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  placeholder="Optional cost in paise"
                  value={estimatedCost}
                  onChange={(e) => setEstimatedCost(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                />
                {estimatedCost && !isNaN(Number(estimatedCost)) && (
                  <span className="text-[11px] font-mono text-metal-500 mt-1 block">
                    ≈ {formatPaiseINR(Number(estimatedCost))}
                  </span>
                )}
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold shadow-xs"
              >
                <Send className="w-3.5 h-3.5" />
                Propose cash event
              </button>
            </div>
          </form>
        </Card>
      )}

      {/* Procurement RFQ Internal Draft */}
      {query.data?.role !== 'VIEWER' && module === 'procurement' && (
        <Card noPadding className="p-5 space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-metal-100 dark:border-metal-800">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <div>
              <h3 className="text-base font-bold text-metal-900 dark:text-white tracking-tight">RFQ internal draft</h3>
              <p className="text-xs text-metal-500 dark:text-metal-400">
                Uses the counterparty, material, date and evidence above.
              </p>
            </div>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () =>
                setDraft(
                  await koshApi.rfqDraft(activeSellerId!, {
                    counterparty_id: Number(party),
                    material_code: material,
                    quantity: Number(quantity),
                    needed_date: day,
                    evidence_ref: evidence,
                  })
                )
              )
            }}
            className="flex flex-col sm:flex-row items-end gap-4"
          >
            <div className="w-full sm:w-64">
              <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                Quantity <span className="text-rose-600">*</span>
              </label>
              <input
                required
                type="number"
                min="1"
                step="1"
                placeholder="e.g. 500"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={!party || !material || !day || !evidence}
              className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold disabled:opacity-50"
            >
              Draft RFQ
            </button>
          </form>
        </Card>
      )}

      {/* RFQ Draft Presentation & T2 Sandbox Send Proposal */}
      {draft && (
        <div className="card p-4 bg-primary-50/40 dark:bg-primary-950/20 border-primary-200 dark:border-primary-800 space-y-3">
          <span className="text-xs font-bold uppercase tracking-wider text-primary-800 dark:text-primary-300">
            Generated Internal Draft (Sandbox)
          </span>
          <p className="text-xs font-mono whitespace-pre-wrap bg-white dark:bg-metal-900 p-3 rounded-xl border border-metal-200 dark:border-metal-700 text-metal-900 dark:text-white">
            {draft.body}
          </p>
          <div className="flex justify-end">
            <button
              onClick={() => void run(() => koshApi.operationIntent(activeSellerId!, draft.id))}
              className="btn-primary inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold shadow-xs"
            >
              Propose T2 sandbox send
            </button>
          </div>
        </div>
      )}

      {/* Pricing / Market Sub-Module */}
      {module === 'pricing' && (
        <div className="space-y-6">
          <Card noPadding className="p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-3">
              <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
              <div>
                <h3 className="text-base font-bold text-metal-900 dark:text-white tracking-tight">
                  Bundled offline market sample · illustrative
                </h3>
                <p className="text-xs text-metal-500 dark:text-metal-400 mt-0.5">
                  Observed price movement across key industrial raw materials and power tariffs.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {query.data?.market_sample?.map((item) => (
                <div
                  key={item.material_code}
                  className="p-3.5 rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 space-y-1 shadow-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-metal-900 dark:text-white">
                      {item.material_code}
                    </span>
                    <span
                      className={`text-xs font-semibold ${
                        Number(item.change_percent) > 0
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-primary-600 dark:text-primary-400'
                      }`}
                    >
                      {item.change_percent}%
                    </span>
                  </div>
                  <p className="text-xs text-metal-500 truncate">
                    {item.material_code} {item.change_percent}% · {item.source}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          {query.data?.role !== 'VIEWER' && (
            <Card noPadding className="p-5 space-y-4">
              <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-3">
                <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
                <h3 className="text-base font-bold text-metal-900 dark:text-white tracking-tight">
                  Propose PO Material Cost Revision
                </h3>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  void run(() =>
                    koshApi.priceProposal(activeSellerId!, {
                      purchase_order_id: Number(po),
                      change_percent: percent,
                      evidence_ref: evidence,
                    })
                  )
                }}
                className="grid grid-cols-1 sm:grid-cols-3 gap-4"
              >
                <div>
                  <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                    Confirmed PO <span className="text-rose-600">*</span>
                  </label>
                  <select
                    required
                    value={po}
                    onChange={(e) => setPo(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                  >
                    <option value="">Select PO</option>
                    {query.data?.items
                      .filter((r) => r.kind === 'PO' && r.status === 'CONFIRMED')
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          PO {r.id}: {r.evidence_ref}
                        </option>
                      ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                    Price change (%) <span className="text-rose-600">*</span>
                  </label>
                  <input
                    required
                    type="number"
                    min="-100"
                    max="100"
                    step="0.01"
                    placeholder="e.g. 8.5"
                    value={percent}
                    onChange={(e) => setPercent(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                    Evidence <span className="text-rose-600">*</span>
                  </label>
                  <input
                    required
                    placeholder="e.g. Supplier price circular"
                    value={evidence}
                    onChange={(e) => setEvidence(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                  />
                </div>

                <div className="sm:col-span-3 flex justify-end">
                  <button type="submit" className="btn-primary px-4 py-2 text-xs font-semibold">
                    Propose cost change
                  </button>
                </div>
              </form>
            </Card>
          )}

          {/* Surcharge Scenario */}
          <Card noPadding className="p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-3">
              <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
              <div>
                <h3 className="text-base font-bold text-metal-900 dark:text-white tracking-tight">Margin pass-through what-if</h3>
                <p className="text-xs text-metal-500 dark:text-metal-400">
                  Uses the price-change percentage and evidence reference above. No receipt or customer
                  amendment is committed.
                </p>
              </div>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void run(async () =>
                  setSurcharge(
                    await koshApi.surchargeScenario(activeSellerId!, Number(sale), percent, evidence)
                  )
                )
              }}
              className="flex flex-col sm:flex-row items-end gap-4"
            >
              <div className="w-full sm:w-72">
                <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
                  Confirmed sale <span className="text-rose-600">*</span>
                </label>
                <select
                  required
                  value={sale}
                  onChange={(e) => setSale(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                >
                  <option value="">Select confirmed sale</option>
                  {query.data?.items
                    .filter((r) => r.kind === 'SALE' && r.status === 'CONFIRMED')
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        Sale {r.id}
                      </option>
                    ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={!percent || !evidence}
                className="btn-primary px-4 py-2 text-xs font-semibold disabled:opacity-50"
              >
                Compute estimated surcharge
              </button>
            </form>

            {surcharge && (
              <div className="mt-4 p-4 rounded-xl bg-metal-50 dark:bg-metal-800/60 border border-metal-200 dark:border-metal-700 space-y-2">
                <span className="text-xs uppercase tracking-wider font-semibold text-metal-500 block">
                  Simulated Pass-Through Impact
                </span>
                <BusinessFields data={surcharge} />
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Operational Resources Component */}
      {(!module ||
        [
          'resources',
          'inventory',
          'supply-chain',
          'workflows',
          'onboarding',
          'goals',
          'knowledge',
          'market',
          'executive',
          'notifications',
        ].includes(module)) && <OperationResources />}

      {/* Internal Order Document Viewer */}
      {document && (
        <Card noPadding className="p-4 space-y-2 border-primary-200 dark:border-primary-800">
          <span className="text-xs font-bold uppercase tracking-wider text-metal-500">
            Internal Order Document
          </span>
          <pre className="whitespace-pre-wrap font-mono text-xs bg-metal-50 dark:bg-metal-800/80 p-4 rounded-xl border border-metal-200 dark:border-metal-700 text-metal-900 dark:text-white">
            {document}
          </pre>
        </Card>
      )}

      {/* Persistent Operational Proposals */}
      <div className="space-y-4 pt-4 border-t border-metal-200/80 dark:border-metal-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <div>
              <h3 className="text-base font-bold text-metal-900 dark:text-white tracking-tight">Persistent operational proposals</h3>
              <p className="text-xs text-metal-500 dark:text-metal-400 mt-0.5">
                Evidence-backed proposals pending owner sign-off or active in operations.
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {query.data?.items?.map((row) => (
            <article
              key={row.id}
              className="card space-y-3 p-4 border-metal-200/80 dark:border-metal-800 bg-white dark:bg-metal-900 hover:border-primary-300 dark:hover:border-primary-700 transition-colors"
            >
              <div className="flex items-center justify-between pb-2 border-b border-metal-100 dark:border-metal-800">
                <h4 className="text-sm font-bold text-metal-900 dark:text-white">
                  {row.kind} #{row.id} · {row.status}
                </h4>
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full font-bold ${
                    row.status === 'CONFIRMED' || row.status === 'COMPLETED'
                      ? 'bg-primary-50 text-primary-800 dark:bg-primary-950/60 dark:text-primary-300 border border-primary-200 dark:border-primary-800'
                      : row.status === 'PROPOSED'
                      ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800'
                      : 'bg-metal-100 text-metal-700 dark:bg-metal-800 dark:text-metal-300 border border-metal-200 dark:border-metal-700'
                  }`}
                >
                  {row.status}
                </span>
              </div>

              <p className="text-xs text-metal-500 font-mono">
                Evidence: <span className="text-metal-900 dark:text-white font-sans">{row.evidence_ref}</span>
              </p>

              <div className="text-xs bg-metal-50 dark:bg-metal-800/50 p-2.5 rounded-xl border border-metal-200/80 dark:border-metal-700">
                <BusinessFields data={row.data} />
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-1">
                {['SALE', 'PO'].includes(row.kind) && (
                  <button
                    onClick={() =>
                      void run(async () =>
                        setDocument((await koshApi.orderDocument(activeSellerId!, row.id)).body)
                      )
                    }
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-metal-200 dark:border-metal-700 text-xs font-semibold text-metal-600 dark:text-metal-300 hover:text-metal-900 dark:hover:text-white hover:bg-metal-100 dark:hover:bg-metal-800 transition-colors"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    View internal order document {row.id}
                  </button>
                )}

                {query.data?.role === 'OWNER' &&
                  row.status === 'PROPOSED' &&
                  ['SALE', 'PO', 'PRICE_CHANGE'].includes(row.kind) && (
                    <button
                      onClick={() => void run(() => koshApi.confirmOrder(activeSellerId!, row.id))}
                      className="btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Owner confirm {row.id}
                    </button>
                  )}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
