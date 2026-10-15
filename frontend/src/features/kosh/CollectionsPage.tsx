import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Scale,
  Calendar,
  AlertCircle,
  FileCheck2,
  Send,
  ExternalLink,
  ShieldAlert,
  Sparkles,
  CheckCircle2,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi, CollectionItem } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
import { formatEnumLabel } from '@/lib/koshLabels'

export const CollectionsPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [message, setMessage] = useState('')
  const [draft, setDraft] = useState<{ id: number; body: string } | null>(null)
  const [channel, setChannel] = useState('EMAIL')
  const [tone, setTone] = useState('PROFESSIONAL')

  // Owner invoice-evidence form state
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | ''>('')
  const [acceptance, setAcceptance] = useState('')
  const [agreement, setAgreement] = useState('UNKNOWN')
  const [days, setDays] = useState('')
  const [evidence, setEvidence] = useState('')
  const [mse, setMse] = useState('UNKNOWN')

  const query = useQuery({
    queryKey: ['kosh', 'collections', activeSellerId],
    queryFn: () => koshApi.collections(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const run = async (task: () => Promise<unknown>) => {
    try {
      await task()
      setMessage('Saved.')
      await qc.invalidateQueries({ queryKey: ['kosh'] })
    } catch (error) {
      setMessage(String(error))
    }
  }

  const invoiceList: CollectionItem[] =
    query.data?.open_invoices && query.data.open_invoices.length > 0
      ? query.data.open_invoices
      : query.data?.items || []

  const selectInvoice = (inv: CollectionItem) => {
    setSelectedInvoiceId(inv.invoice_id)
    if (inv.terms) {
      setAcceptance(inv.terms.acceptance_date || '')
      setAgreement(inv.terms.agreement_status || 'UNKNOWN')
      setDays(inv.terms.agreed_days != null ? String(inv.terms.agreed_days) : '')
      setMse(
        inv.terms.supplier_mse === true
          ? 'APPLICABLE'
          : inv.terms.supplier_mse === false
          ? 'NOT_APPLICABLE'
          : 'UNKNOWN'
      )
      setEvidence(inv.terms.evidence_ref || '')
    } else {
      setAcceptance('')
      setAgreement('UNKNOWN')
      setDays('')
      setMse('UNKNOWN')
      setEvidence('')
    }
  }

  const handleSaveTerms = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedInvoiceId) return
    await run(async () => {
      await koshApi.collectionTerms(activeSellerId!, Number(selectedInvoiceId), {
        acceptance_date: acceptance ? acceptance : null,
        agreement_status: agreement,
        agreed_days: agreement === 'AGREED' ? (days ? Number(days) : null) : null,
        supplier_mse: mse === 'APPLICABLE' ? true : mse === 'NOT_APPLICABLE' ? false : null,
        evidence_ref: evidence.trim() || null,
      })
    })
  }

  const fixture = query.data?.fixture
  const asOfDate = query.data?.as_of || '2026-10-13'

  return (
    <section aria-label="Collections" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Scale size={20} className="text-blue-600" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Collections & Statutory Interest</h2>
          </div>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            MSMED Act Section 16 monthly-rest compound interest at 3× configured RBI bank rate.
            Section 15 limits agreed credit to 45 days (15 days if none agreed).
          </p>
        </div>
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-100 text-xs font-semibold text-slate-700 border border-slate-200 self-start sm:self-auto">
          <Calendar size={13} className="text-slate-500" />
          <span>Calculation as-of: <strong>{asOfDate}</strong></span>
        </div>
      </div>

      {message && (
        <div role="status" className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs font-semibold text-emerald-800 flex items-center gap-2">
          <CheckCircle2 size={14} className="text-emerald-600 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {/* Separately labelled fictional demonstration fixture */}
      {fixture && (
        <div className="rounded-2xl border border-purple-200 bg-gradient-to-br from-purple-50/90 to-indigo-50/50 p-5 space-y-3 shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-purple-100 pb-2.5">
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-purple-700" />
              <h3 className="font-bold text-purple-950 text-sm tracking-tight">{fixture.label}</h3>
            </div>
            <span className="self-start sm:self-auto rounded-full bg-purple-200/80 text-purple-900 px-2.5 py-0.5 text-xs font-bold border border-purple-300">
              Demonstration Only (Fictional)
            </span>
          </div>

          <p className="text-xs text-purple-800 leading-relaxed">{fixture.note}</p>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs pt-1">
            <div className="card p-3 border-purple-100/80">
              <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider block">Invoice / Buyer</span>
              <strong className="text-slate-900 block mt-0.5 text-xs sm:text-sm">{fixture.invoice_number}</strong>
              <div className="text-slate-600 text-xs truncate">{fixture.party}</div>
            </div>

            <div className="card p-3 border-purple-100/80">
              <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider block">Principal</span>
              <strong className="text-slate-900 block mt-0.5 text-xs sm:text-sm">{formatPaiseINR(fixture.principal_paise)}</strong>
            </div>

            <div className="card p-3 border-purple-100/80">
              <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider block">Overdue Interest</span>
              <strong className="text-purple-700 block mt-0.5 text-xs sm:text-sm">{formatPaiseINR(fixture.interest.interest_paise)}</strong>
              <div className="text-[10px] text-slate-500">17.25% p.a., 2 rests</div>
            </div>

            <div className="card p-3 border-purple-100/80">
              <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider block">Total Claim</span>
              <strong className="text-purple-900 block mt-0.5 text-xs sm:text-sm">{formatPaiseINR(fixture.total_paise)}</strong>
            </div>
          </div>

          <p className="text-[11px] text-purple-700 font-medium">
            Terms: Accepted {fixture.acceptance_date} · No agreed credit (15 days under Section 15, due {fixture.due_date}) · MSE Applicable · {fixture.overdue_days} days overdue as of {fixture.as_of}.
          </p>
        </div>
      )}

      {/* Owner invoice-evidence form */}
      {query.data?.role === 'OWNER' && (
        <form
          onSubmit={handleSaveTerms}
          className="card p-5 space-y-4 border-blue-200"
        >
          <div className="border-b border-slate-100 pb-3">
            <div className="flex items-center gap-2">
              <FileCheck2 size={16} className="text-blue-600" />
              <h3 className="text-base font-bold text-slate-900 tracking-tight">
                Document Invoice Evidence & Payment Terms
              </h3>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Owner only. Unknown facts must stay unknown. Recording evidence writes to the audit chain and does not move money or bypass approvals.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="evidence-invoice-select" className="label">
                Select open invoice
              </label>
              <select
                id="evidence-invoice-select"
                required
                className="select text-xs"
                value={selectedInvoiceId}
                onChange={(e) => {
                  const id = Number(e.target.value)
                  setSelectedInvoiceId(id || '')
                  const target = invoiceList.find((x) => x.invoice_id === id)
                  if (target) selectInvoice(target)
                }}
              >
                <option value="">-- Choose an open receivable --</option>
                {invoiceList.map((inv) => (
                  <option key={inv.invoice_id} value={inv.invoice_id}>
                    {inv.invoice_number} · {inv.party} · {formatPaiseINR(inv.amount_paise)} (Due: {inv.due_date || 'N/A'}{inv.is_overdue ? ' - OVERDUE' : ''})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="evidence-acceptance-date" className="label">
                Acceptance date
              </label>
              <input
                id="evidence-acceptance-date"
                type="date"
                className="input text-xs"
                value={acceptance}
                max={asOfDate}
                onChange={(e) => setAcceptance(e.target.value)}
              />
              <span className="text-[11px] text-slate-400 mt-1 block">Leave blank if unknown</span>
            </div>

            <div>
              <label htmlFor="evidence-payment-terms" className="label">
                Payment terms
              </label>
              <select
                id="evidence-payment-terms"
                aria-label="Payment terms"
                className="select text-xs"
                value={agreement}
                onChange={(e) => setAgreement(e.target.value)}
              >
                <option value="UNKNOWN">Unknown / Not agreed</option>
                <option value="NONE">None agreed (15-day Section 15 rule)</option>
                <option value="AGREED">Agreed period (contractually agreed)</option>
              </select>
            </div>

            {agreement === 'AGREED' ? (
              <div>
                <label htmlFor="evidence-agreed-days" className="label">
                  Agreed period in days
                </label>
                <input
                  id="evidence-agreed-days"
                  required
                  type="number"
                  min="0"
                  max="45"
                  placeholder="e.g. 30 (statutory max 45)"
                  className="input text-xs"
                  value={days}
                  onChange={(e) => setDays(e.target.value)}
                />
                <span className="text-[11px] text-slate-400 mt-1 block">Agreed credit cannot exceed 45 days under Section 15</span>
              </div>
            ) : (
              <div>
                <label className="label">
                  Applicable statutory period
                </label>
                <input
                  disabled
                  readOnly
                  type="text"
                  className="input text-xs bg-slate-50 text-slate-500 cursor-not-allowed"
                  value={agreement === 'NONE' ? '15 days (Section 15 default)' : 'Unknown / Review Required'}
                />
              </div>
            )}

            <div>
              <label htmlFor="evidence-supplier-mse" className="label">
                Micro/Small enterprise applicability
              </label>
              <select
                id="evidence-supplier-mse"
                aria-label="Micro/Small enterprise applicability"
                className="select text-xs"
                value={mse}
                onChange={(e) => setMse(e.target.value)}
              >
                <option value="UNKNOWN">Unknown / Unverified</option>
                <option value="APPLICABLE">Applicable (Micro / Small Enterprise)</option>
                <option value="NOT_APPLICABLE">Not applicable (Statutory interest does not apply)</option>
              </select>
            </div>

            <div>
              <label htmlFor="evidence-ref-note" className="label">
                Supporting evidence reference or note
              </label>
              <input
                id="evidence-ref-note"
                type="text"
                maxLength={160}
                placeholder="e.g. PO clause 4.2 / Udyam registration"
                className="input text-xs"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
              />
            </div>
          </div>

          <div className="pt-2 flex flex-col sm:flex-row items-center gap-3">
            <button
              type="submit"
              disabled={!selectedInvoiceId}
              className="btn-primary text-xs py-2 px-5 w-full sm:w-auto"
            >
              Save Documented Terms
            </button>
            {selectedInvoiceId && (
              <button
                type="button"
                onClick={() => {
                  setSelectedInvoiceId('')
                  setAcceptance('')
                  setAgreement('UNKNOWN')
                  setDays('')
                  setMse('UNKNOWN')
                  setEvidence('')
                }}
                className="text-xs text-slate-500 hover:text-slate-800"
              >
                Clear selection
              </button>
            )}
          </div>
        </form>
      )}

      {/* Receivables & Statutory Interest table */}
      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-bold text-sm text-slate-900 tracking-tight">Receivables & Statutory Calculation</h3>
          <span className="text-xs text-slate-500">{invoiceList.length} invoices</span>
        </div>

        {invoiceList.length === 0 ? (
          <p className="p-8 text-center text-xs text-slate-400">No open receivables found.</p>
        ) : (
          <div className="table-container border-0 shadow-none rounded-none">
            <table>
              <thead>
                <tr>
                  <th>Invoice / Customer</th>
                  <th>Principal</th>
                  <th>Statutory Interest</th>
                  <th>Total Claim</th>
                  <th>Owner-entered Evidence</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {invoiceList.map((row) => {
                  const interestPaise = row.interest?.interest_paise
                  const isReview = row.interest?.status === 'REVIEW_REQUIRED'
                  const isNotApplicable = row.interest?.status === 'NOT_APPLICABLE'
                  const isComputed = row.interest?.status === 'COMPUTED'
                  const isOverdue = (row.interest?.overdue_days || 0) > 0
                  const totalClaim = row.total_paise ?? (row.amount_paise + (interestPaise || 0))

                  return (
                    <tr key={row.invoice_id} className="hover:bg-slate-50/70">
                      <td className="py-3">
                        <strong className="text-slate-900 block">{row.invoice_number}</strong>
                        <div className="text-slate-600 text-xs">{row.party}</div>
                        <div className="text-[10px] text-slate-400">Due: {row.due_date || 'N/A'}</div>
                      </td>
                      <td className="font-semibold text-slate-900">
                        {formatPaiseINR(row.amount_paise)}
                      </td>
                      <td>
                        {isReview && (
                          <div>
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-200">
                              <AlertCircle size={10} />
                              REVIEW REQUIRED
                            </span>
                            <div className="text-[10px] text-slate-500 mt-0.5">No statutory debt computed</div>
                          </div>
                        )}
                        {isNotApplicable && (
                          <div>
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-600 border border-slate-200">
                              NOT APPLICABLE
                            </span>
                            <div className="text-[10px] text-slate-500 mt-0.5">Statutory interest does not apply</div>
                          </div>
                        )}
                        {isComputed && !isOverdue && (
                          <div>
                            <strong className="text-blue-700">{formatPaiseINR(0)}</strong>
                            <div className="text-[10px] text-blue-600 font-medium">Not yet overdue</div>
                          </div>
                        )}
                        {isComputed && isOverdue && (
                          <div>
                            <strong className="text-rose-700">{formatPaiseINR(interestPaise)}</strong>
                            <div className="text-[10px] text-slate-500">
                              {Number(row.interest?.annual_rate ?? 0) * 100}% p.a. · {row.interest?.monthly_rests} rests
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="font-bold text-slate-900">
                        {formatPaiseINR(totalClaim)}
                      </td>
                      <td className="text-[11px] text-slate-600 max-w-xs">
                        {row.terms ? (
                          <div className="space-y-0.5">
                            <div>Accepted: <span className="font-medium">{row.terms.acceptance_date || 'Unknown'}</span></div>
                            <div>Terms: <span className="font-medium">{row.terms.agreement_status}{row.terms.agreed_days != null ? ` (${row.terms.agreed_days}d)` : ''}</span></div>
                            <div>MSE: <span className="font-medium">{row.terms.supplier_mse === true ? 'Yes' : row.terms.supplier_mse === false ? 'No' : 'Unknown'}</span></div>
                            {row.evidence_ref && <div className="text-slate-400 italic">Ref: {row.evidence_ref}</div>}
                          </div>
                        ) : (
                          <span className="text-slate-400 italic">No evidence recorded</span>
                        )}
                      </td>
                      <td>
                        <div className="flex flex-col sm:flex-row gap-1.5">
                          {query.data?.role === 'OWNER' && (
                            <button
                              onClick={() => selectInvoice(row)}
                              className="btn-secondary text-[11px] py-1 px-2.5 font-semibold"
                            >
                              Edit evidence
                            </button>
                          )}
                          {query.data?.role !== 'VIEWER' && (
                            <button
                              onClick={() =>
                                void run(async () =>
                                  setDraft(
                                    await koshApi.reminderDraft(
                                      activeSellerId!,
                                      row.invoice_id,
                                      tone,
                                      channel
                                    )
                                  )
                                )
                              }
                              className="btn-ghost text-[11px] py-1 px-2.5"
                            >
                              Draft reminder
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Reminder outreach section */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
          <Send size={16} className="text-blue-600" />
          <h3 className="font-bold text-sm text-slate-900 tracking-tight">Outreach Configuration</h3>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Sandbox channel</label>
            <select
              className="select text-xs"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              <option>EMAIL</option>
              <option>WHATSAPP</option>
            </select>
          </div>
          <div>
            <label className="label">Tone</label>
            <select
              className="select text-xs"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
            >
              <option>GENTLE</option>
              <option>PROFESSIONAL</option>
              <option>FIRM</option>
            </select>
          </div>
        </div>

        {draft && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 space-y-2.5 text-xs">
            <h4 className="font-bold text-amber-900">T1 Internal Reminder Draft</h4>
            <p className="text-slate-800 whitespace-pre-wrap font-mono text-[11px] bg-white/70 p-3 rounded-lg border border-amber-200">
              {draft.body}
            </p>
            <div className="flex flex-wrap gap-3 pt-1 items-center">
              <button
                onClick={() => void run(() => koshApi.reminderIntent(activeSellerId!, draft.id))}
                className="btn-primary text-xs py-1.5 px-3.5 bg-amber-700 hover:bg-amber-800"
              >
                Propose T2 send
              </button>
              <Link to="/approvals" className="text-amber-900 font-semibold underline hover:text-amber-950 flex items-center gap-1">
                Review in Approvals
                <ExternalLink size={11} />
              </Link>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

