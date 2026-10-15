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
import { SandboxBanner } from '@/components/ui/SandboxBanner'
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
    <section aria-label="Operations" className="space-y-8 animate-fadeIn">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-border">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-brand-navy/10 dark:bg-brand-gold/10 text-brand-navy dark:text-brand-gold border border-brand-navy/20 dark:border-brand-gold/20 mb-2">
            <Briefcase className="w-3.5 h-3.5" />
            Operations Command Center
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">
            Operations · {activeTab}
          </h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Propose evidence-backed sales, procurement, pricing changes and operational workflows.
            Cash impact remains excluded until explicit owner confirmation.
          </p>
        </div>
      </div>

      {/* Operations Sub-Navigation Bar */}
      <nav className="flex items-center gap-2 overflow-x-auto pb-2 border-b border-border text-xs scrollbar-none">
        {navLinks.map((link) => {
          const isActive =
            link.to === `/operations/${module}` ||
            (link.to === '/operations/resources' && !module)
          return (
            <Link
              key={link.to}
              to={link.to}
              className={`px-3 py-2 rounded-lg font-medium whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                isActive
                  ? 'bg-foreground text-background font-semibold shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
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
        <div className="p-3.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
          <p role="status">{message}</p>
        </div>
      )}

      {query.isError && (
        <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-900 dark:text-rose-200 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
          <p role="alert">Unable to load operations.</p>
        </div>
      )}

      {/* Sales / Procurement Proposal Forms */}
      {query.data?.role !== 'VIEWER' && ['sales', 'procurement'].includes(module ?? '') && (
        <div className="card space-y-5">
          <div className="flex items-center gap-2 pb-3 border-b border-border">
            <div className="p-1.5 rounded-md bg-brand-gold/15 text-brand-navy dark:text-brand-gold">
              {module === 'sales' ? (
                <ShoppingCart className="w-4 h-4" />
              ) : (
                <PackageCheck className="w-4 h-4" />
              )}
            </div>
            <div>
              <h3 className="text-base font-semibold text-foreground">
                {module === 'sales' ? 'Confirmed-sales proposal' : 'Purchase-order proposal'}
              </h3>
              <p className="text-xs text-muted-foreground">
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
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Counterparty <span className="text-rose-600">*</span>
                </label>
                <select
                  required
                  value={party}
                  onChange={(e) => setParty(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                >
                  <option value="">Select counterparty</option>
                  {query.data?.counterparties.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
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
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                />
                {amount && !isNaN(Number(amount)) && (
                  <span className="text-[11px] font-mono text-emerald-700 dark:text-emerald-400 mt-0.5 block">
                    ≈ {formatPaiseINR(Number(amount))}
                  </span>
                )}
              </div>

              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Payment date <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  type="date"
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Material code <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  pattern="[A-Z0-9_-]{1,40}"
                  placeholder="e.g. MAT-STEEL-01"
                  value={material}
                  onChange={(e) => setMaterial(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors uppercase font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Evidence reference <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  placeholder="e.g. PO-2026-904, Signed Contract"
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Documented estimated cost (paise; optional)
                </label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  placeholder="Optional cost in paise"
                  value={estimatedCost}
                  onChange={(e) => setEstimatedCost(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                />
                {estimatedCost && !isNaN(Number(estimatedCost)) && (
                  <span className="text-[11px] font-mono text-muted-foreground mt-0.5 block">
                    ≈ {formatPaiseINR(Number(estimatedCost))}
                  </span>
                )}
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold shadow-sm"
              >
                <Send className="w-3.5 h-3.5 text-brand-gold" />
                Propose cash event
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Procurement RFQ Internal Draft */}
      {query.data?.role !== 'VIEWER' && module === 'procurement' && (
        <div className="card space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-border">
            <div className="p-1.5 rounded-md bg-brand-navy/10 text-brand-navy dark:bg-brand-gold/10 dark:text-brand-gold">
              <FileText className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-foreground">RFQ internal draft</h3>
              <p className="text-xs text-muted-foreground">
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
              <label className="block text-xs font-semibold text-foreground mb-1.5">
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
                className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={!party || !material || !day || !evidence}
              className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold disabled:opacity-50"
            >
              Draft RFQ
            </button>
          </form>
        </div>
      )}

      {/* RFQ Draft Presentation & T2 Sandbox Send Proposal */}
      {draft && (
        <div className="card p-4 bg-muted/30 border-border space-y-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Generated Internal Draft (Sandbox)
          </span>
          <p className="text-sm font-mono whitespace-pre-wrap bg-background p-3 rounded-lg border border-border text-foreground">
            {draft.body}
          </p>
          <div className="flex justify-end">
            <button
              onClick={() => void run(() => koshApi.operationIntent(activeSellerId!, draft.id))}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-foreground text-background text-xs font-semibold hover:opacity-90 transition-opacity"
            >
              Propose T2 sandbox send
            </button>
          </div>
        </div>
      )}

      {/* Pricing / Market Sub-Module */}
      {module === 'pricing' && (
        <div className="space-y-6">
          <div className="card space-y-4">
            <div>
              <h3 className="text-base font-semibold text-foreground">
                Bundled offline market sample · illustrative
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                Observed price movement across key industrial raw materials and power tariffs.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {query.data?.market_sample.map((item) => (
                <div
                  key={item.material_code}
                  className="p-3 rounded-lg border border-border bg-card space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-foreground">
                      {item.material_code}
                    </span>
                    <span
                      className={`text-xs font-semibold ${
                        Number(item.change_percent) > 0
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-emerald-600 dark:text-emerald-400'
                      }`}
                    >
                      {item.change_percent}%
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground truncate">
                    {item.material_code} {item.change_percent}% · {item.source}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {query.data?.role !== 'VIEWER' && (
            <div className="card space-y-4">
              <h3 className="text-base font-semibold text-foreground">
                Propose PO Material Cost Revision
              </h3>
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
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Confirmed PO <span className="text-rose-600">*</span>
                  </label>
                  <select
                    required
                    value={po}
                    onChange={(e) => setPo(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
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
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
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
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Evidence <span className="text-rose-600">*</span>
                  </label>
                  <input
                    required
                    placeholder="e.g. Supplier price circular"
                    value={evidence}
                    onChange={(e) => setEvidence(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
                  />
                </div>

                <div className="sm:col-span-3 flex justify-end">
                  <button type="submit" className="btn-primary px-4 py-2 text-sm font-semibold">
                    Propose cost change
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Surcharge Scenario */}
          <div className="card space-y-4">
            <h3 className="text-base font-semibold text-foreground">Margin pass-through what-if</h3>
            <p className="text-xs text-muted-foreground">
              Uses the price-change percentage and evidence reference above. No receipt or customer
              amendment is committed.
            </p>
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
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Confirmed sale <span className="text-rose-600">*</span>
                </label>
                <select
                  required
                  value={sale}
                  onChange={(e) => setSale(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-brand-gold/40 focus:border-brand-gold transition-colors"
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
                className="btn-primary px-4 py-2 text-sm font-semibold disabled:opacity-50"
              >
                Compute estimated surcharge
              </button>
            </form>

            {surcharge && (
              <div className="mt-4 p-4 rounded-xl bg-muted/40 border border-border space-y-2">
                <span className="text-xs uppercase tracking-wider font-semibold text-muted-foreground block">
                  Simulated Pass-Through Impact
                </span>
                <BusinessFields data={surcharge} />
              </div>
            )}
          </div>
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
        <div className="card space-y-2 border-brand-gold/30">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Internal Order Document
          </span>
          <pre className="whitespace-pre-wrap font-mono text-xs bg-muted/30 p-4 rounded-lg border border-border text-foreground">
            {document}
          </pre>
        </div>
      )}

      {/* Persistent Operational Proposals */}
      <div className="space-y-4 pt-4 border-t border-border">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-foreground">Persistent operational proposals</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Evidence-backed proposals pending owner sign-off or active in operations.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {query.data?.items.map((row) => (
            <article
              key={row.id}
              className="card space-y-3 p-4 border-border bg-card hover:border-brand-gold/30 transition-colors"
            >
              <div className="flex items-center justify-between pb-2 border-b border-border/60">
                <h4 className="text-sm font-bold text-foreground">
                  {row.kind} #{row.id} · {row.status}
                </h4>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                    row.status === 'CONFIRMED' || row.status === 'COMPLETED'
                      ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                      : row.status === 'PROPOSED'
                      ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800'
                      : 'bg-muted text-muted-foreground border border-border'
                  }`}
                >
                  {row.status}
                </span>
              </div>

              <p className="text-xs text-muted-foreground font-mono">
                Evidence: <span className="text-foreground">{row.evidence_ref}</span>
              </p>

              <div className="text-xs bg-muted/20 p-2.5 rounded-lg border border-border/50">
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
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
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
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold transition-colors"
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
