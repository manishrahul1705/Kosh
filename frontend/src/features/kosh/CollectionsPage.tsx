import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
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
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Collections & Statutory Interest</h2>
          <p className="text-sm text-gray-600">
            MSMED Act Section 16 monthly-rest compound interest at 3× configured RBI bank rate.
            Section 15 limits agreed credit to 45 days (15 days if none agreed).
          </p>
        </div>
        <div className="inline-block rounded-md bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
          Calculation as-of: <strong>{asOfDate}</strong>
        </div>
      </div>

      {message && (
        <p role="status" className="rounded-md bg-blue-50 p-3 text-sm text-blue-800">
          {message}
        </p>
      )}

      {/* Separately labelled fictional demonstration fixture */}
      {fixture && (
        <div className="rounded-lg border border-purple-200 bg-purple-50 p-4 space-y-2">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
            <h3 className="font-semibold text-purple-900 text-sm">{fixture.label}</h3>
            <span className="self-start rounded bg-purple-200 px-2 py-0.5 text-xs font-medium text-purple-800">
              Demonstration Only (Fictional)
            </span>
          </div>
          <p className="text-xs text-purple-700">{fixture.note}</p>
          <div className="grid grid-cols-2 gap-3 pt-1 sm:grid-cols-4 text-xs">
            <div className="rounded bg-white p-2 border border-purple-100">
              <span className="text-gray-500 block">Invoice / Buyer</span>
              <strong>{fixture.invoice_number}</strong>
              <div className="text-gray-600">{fixture.party}</div>
            </div>
            <div className="rounded bg-white p-2 border border-purple-100">
              <span className="text-gray-500 block">Principal</span>
              <strong>{formatPaiseINR(fixture.principal_paise)}</strong>
            </div>
            <div className="rounded bg-white p-2 border border-purple-100">
              <span className="text-gray-500 block">Overdue Interest</span>
              <strong className="text-purple-700">{formatPaiseINR(fixture.interest.interest_paise)}</strong>
              <div className="text-[10px] text-gray-500">17.25% p.a., 2 rests</div>
            </div>
            <div className="rounded bg-white p-2 border border-purple-100">
              <span className="text-gray-500 block">Total Claim</span>
              <strong className="text-purple-900">{formatPaiseINR(fixture.total_paise)}</strong>
            </div>
          </div>
          <p className="text-[11px] text-purple-600">
            Terms: Accepted {fixture.acceptance_date} · No agreed credit (15 days under Section 15, due {fixture.due_date}) · MSE Applicable · {fixture.overdue_days} days overdue as of {fixture.as_of}.
          </p>
        </div>
      )}

      {/* Owner invoice-evidence form */}
      {query.data?.role === 'OWNER' && (
        <form
          onSubmit={handleSaveTerms}
          className="rounded-xl border border-blue-200 bg-white p-5 shadow-sm space-y-4"
        >
          <div className="border-b pb-3">
            <h3 className="text-base font-semibold text-gray-900">
              Document Invoice Evidence & Payment Terms
            </h3>
            <p className="text-xs text-gray-500">
              Owner only. Unknown facts must stay unknown. Recording evidence writes to the audit chain and does not move money or bypass approvals.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="evidence-invoice-select" className="block text-xs font-semibold text-gray-700 mb-1">
                Select open invoice
              </label>
              <select
                id="evidence-invoice-select"
                required
                className="w-full rounded-md border border-gray-300 p-2 text-sm bg-white"
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
              <label htmlFor="evidence-acceptance-date" className="block text-xs font-semibold text-gray-700 mb-1">
                Acceptance date
              </label>
              <input
                id="evidence-acceptance-date"
                type="date"
                className="w-full rounded-md border border-gray-300 p-2 text-sm bg-white"
                value={acceptance}
                max={asOfDate}
                onChange={(e) => setAcceptance(e.target.value)}
              />
              <span className="text-[11px] text-gray-500">Leave blank if unknown</span>
            </div>

            <div>
              <label htmlFor="evidence-payment-terms" className="block text-xs font-semibold text-gray-700 mb-1">
                Payment terms
              </label>
              <select
                id="evidence-payment-terms"
                className="w-full rounded-md border border-gray-300 p-2 text-sm bg-white"
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
                <label htmlFor="evidence-agreed-days" className="block text-xs font-semibold text-gray-700 mb-1">
                  Agreed period in days
                </label>
                <input
                  id="evidence-agreed-days"
                  required
                  type="number"
                  min="0"
                  max="45"
                  placeholder="e.g. 30 (statutory max 45)"
                  className="w-full rounded-md border border-gray-300 p-2 text-sm bg-white"
                  value={days}
                  onChange={(e) => setDays(e.target.value)}
                />
                <span className="text-[11px] text-gray-500">Agreed credit cannot exceed 45 days under Section 15</span>
              </div>
            ) : (
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Applicable statutory period
                </label>
                <input
                  disabled
                  readOnly
                  type="text"
                  className="w-full rounded-md border border-gray-200 bg-gray-50 p-2 text-sm text-gray-500"
                  value={agreement === 'NONE' ? '15 days (Section 15 default)' : 'Unknown / Review Required'}
                />
              </div>
            )}

            <div>
              <label htmlFor="evidence-supplier-mse" className="block text-xs font-semibold text-gray-700 mb-1">
                Micro/Small enterprise applicability
              </label>
              <select
                id="evidence-supplier-mse"
                className="w-full rounded-md border border-gray-300 p-2 text-sm bg-white"
                value={mse}
                onChange={(e) => setMse(e.target.value)}
              >
                <option value="UNKNOWN">Unknown / Unverified</option>
                <option value="APPLICABLE">Applicable (Micro / Small Enterprise)</option>
                <option value="NOT_APPLICABLE">Not applicable (Statutory interest does not apply)</option>
              </select>
            </div>

            <div>
              <label htmlFor="evidence-ref-note" className="block text-xs font-semibold text-gray-700 mb-1">
                Supporting evidence reference or note
              </label>
              <input
                id="evidence-ref-note"
                type="text"
                maxLength={160}
                placeholder="e.g. PO clause 4.2 / Udyam registration"
                className="w-full rounded-md border border-gray-300 p-2 text-sm bg-white"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
              />
            </div>
          </div>

          <div className="pt-2 flex flex-col sm:flex-row items-center gap-3">
            <button
              type="submit"
              disabled={!selectedInvoiceId}
              className="w-full sm:w-auto rounded-md bg-blue-600 px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
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
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                Clear selection
              </button>
            )}
          </div>
        </form>
      )}

      {/* Receivables & Statutory Interest table */}
      <div className="space-y-3">
        <h3 className="text-base font-semibold text-gray-900">Receivables & Statutory Calculation</h3>
        {invoiceList.length === 0 ? (
          <p className="text-sm text-gray-500">No open receivables found.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-left text-xs">
              <thead className="bg-gray-50 border-b text-gray-600">
                <tr>
                  <th className="p-3">Invoice / Customer</th>
                  <th className="p-3">Principal</th>
                  <th className="p-3">Statutory Interest</th>
                  <th className="p-3">Total Claim</th>
                  <th className="p-3">Owner-entered Evidence</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {invoiceList.map((row) => {
                  const interestPaise = row.interest?.interest_paise
                  const isReview = row.interest?.status === 'REVIEW_REQUIRED'
                  const isNotApplicable = row.interest?.status === 'NOT_APPLICABLE'
                  const isComputed = row.interest?.status === 'COMPUTED'
                  const isOverdue = (row.interest?.overdue_days || 0) > 0
                  const totalClaim = row.total_paise ?? (row.amount_paise + (interestPaise || 0))

                  return (
                    <tr key={row.invoice_id} className="hover:bg-gray-50">
                      <td className="p-3">
                        <strong className="text-gray-900">{row.invoice_number}</strong>
                        <div className="text-gray-500">{row.party}</div>
                        <div className="text-[10px] text-gray-400">Due: {row.due_date || 'N/A'}</div>
                      </td>
                      <td className="p-3 font-medium text-gray-900">
                        {formatPaiseINR(row.amount_paise)}
                      </td>
                      <td className="p-3">
                        {isReview && (
                          <div>
                            <span className="inline-block rounded bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                              REVIEW REQUIRED
                            </span>
                            <div className="text-[11px] text-gray-500 mt-0.5">No statutory debt computed</div>
                          </div>
                        )}
                        {isNotApplicable && (
                          <div>
                            <span className="inline-block rounded bg-gray-100 px-2 py-0.5 text-[10px] font-semibold text-gray-600">
                              NOT APPLICABLE
                            </span>
                            <div className="text-[11px] text-gray-500 mt-0.5">Statutory interest does not apply</div>
                          </div>
                        )}
                        {isComputed && !isOverdue && (
                          <div>
                            <strong className="text-blue-700">{formatPaiseINR(0)}</strong>
                            <div className="text-[10px] text-blue-600">Not yet overdue</div>
                          </div>
                        )}
                        {isComputed && isOverdue && (
                          <div>
                            <strong className="text-red-700">{formatPaiseINR(interestPaise)}</strong>
                            <div className="text-[10px] text-gray-500">
                              {Number(row.interest.annual_rate) * 100}% p.a. · {row.interest.monthly_rests} rests
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="p-3 font-semibold text-gray-900">
                        {formatPaiseINR(totalClaim)}
                      </td>
                      <td className="p-3 text-[11px] text-gray-600 max-w-xs">
                        {row.terms ? (
                          <div>
                            <div>Accepted: {row.terms.acceptance_date || 'Unknown'}</div>
                            <div>Terms: {row.terms.agreement_status}{row.terms.agreed_days != null ? ` (${row.terms.agreed_days}d)` : ''}</div>
                            <div>MSE: {row.terms.supplier_mse === true ? 'Yes' : row.terms.supplier_mse === false ? 'No' : 'Unknown'}</div>
                            {row.evidence_ref && <div className="text-gray-500 italic">Ref: {row.evidence_ref}</div>}
                          </div>
                        ) : (
                          <span className="text-gray-400 italic">No evidence recorded</span>
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex flex-col sm:flex-row gap-1.5">
                          {query.data?.role === 'OWNER' && (
                            <button
                              onClick={() => selectInvoice(row)}
                              className="rounded border border-blue-600 px-2.5 py-1 text-[11px] font-medium text-blue-600 hover:bg-blue-50"
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
                              className="rounded border border-gray-300 px-2.5 py-1 text-[11px] font-medium text-gray-700 hover:bg-gray-50"
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
      <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">Outreach Configuration</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs font-medium text-gray-700">
            Sandbox channel
            <select
              className="mt-1 block w-full rounded border border-gray-300 p-1.5 text-xs bg-white"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              <option>EMAIL</option>
              <option>WHATSAPP</option>
            </select>
          </label>
          <label className="block text-xs font-medium text-gray-700">
            Tone
            <select
              className="mt-1 block w-full rounded border border-gray-300 p-1.5 text-xs bg-white"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
            >
              <option>GENTLE</option>
              <option>PROFESSIONAL</option>
              <option>FIRM</option>
            </select>
          </label>
        </div>

        {draft && (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 space-y-2 text-xs">
            <h4 className="font-semibold text-amber-900">T1 Internal Reminder Draft</h4>
            <p className="text-gray-800 whitespace-pre-wrap">{draft.body}</p>
            <div className="flex gap-2 pt-1 items-center">
              <button
                onClick={() => void run(() => koshApi.reminderIntent(activeSellerId!, draft.id))}
                className="rounded bg-amber-700 px-3 py-1 font-medium text-white hover:bg-amber-800"
              >
                Propose T2 send
              </button>
              <Link to="/approvals" className="text-amber-800 underline">
                Review in Approvals
              </Link>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
