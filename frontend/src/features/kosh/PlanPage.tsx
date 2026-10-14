import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useSeller } from '@/app/SellerContext'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { koshApi, FinancingEvidencePayload } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'

export const PlanPage = () => {
  const { activeSellerId } = useSeller()
  const [target, setTarget] = useState('0.20')
  const qc = useQueryClient()

  const options = useQuery({
    queryKey: ['kosh', 'financing', activeSellerId],
    queryFn: () => koshApi.financingOptions(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
  })

  const evidenceQuery = useQuery({
    queryKey: ['kosh', 'financing-evidence', activeSellerId],
    queryFn: () => koshApi.financingEvidence(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
  })

  const curve = useQuery({
    queryKey: ['kosh', 'safety-curve', activeSellerId],
    queryFn: () => koshApi.safetyCurve(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
    staleTime: 60000,
  })

  const plan = useQuery({
    queryKey: ['kosh', 'plan', activeSellerId],
    queryFn: () => koshApi.latestPlan(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
  })

  const evaluate = useMutation({
    mutationFn: () => koshApi.evaluateFinancing(activeSellerId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kosh', 'financing', activeSellerId] })
      qc.invalidateQueries({ queryKey: ['kosh', 'safety-curve', activeSellerId] })
    },
  })

  const propose = useMutation({
    mutationFn: () => koshApi.createPlan(activeSellerId!, target),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kosh', 'plan', activeSellerId] }),
  })

  // Evidence form state
  const [nonCorporate, setNonCorporate] = useState<'UNKNOWN' | 'YES' | 'NO'>('UNKNOWN')
  const [nonFarm, setNonFarm] = useState<'UNKNOWN' | 'YES' | 'NO'>('UNKNOWN')
  const [incomeGenerating, setIncomeGenerating] = useState<'UNKNOWN' | 'YES' | 'NO'>('UNKNOWN')
  const [mseStatus, setMseStatus] = useState<'UNKNOWN' | 'YES' | 'NO'>('UNKNOWN')
  const [udyamCert, setUdyamCert] = useState<'UNKNOWN' | 'YES' | 'NO'>('UNKNOWN')
  const [gemPoDoc, setGemPoDoc] = useState<'UNKNOWN' | 'YES' | 'NO'>('UNKNOWN')
  const [relMonths, setRelMonths] = useState<string>('')
  const [onTimeRatio, setOnTimeRatio] = useState<string>('')
  const [extensionStatus, setExtensionStatus] = useState<'UNKNOWN' | 'PROPOSED' | 'CONFIRMED'>('UNKNOWN')
  const [evidenceRef, setEvidenceRef] = useState<string>('')
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)
  const [selectedFixture, setSelectedFixture] = useState<string>('')

  // Preload evidence into form when query loads
  useEffect(() => {
    if (evidenceQuery.data?.evidence) {
      const ev = evidenceQuery.data.evidence
      setNonCorporate(ev.non_corporate === true ? 'YES' : ev.non_corporate === false ? 'NO' : 'UNKNOWN')
      setNonFarm(ev.non_farm === true ? 'YES' : ev.non_farm === false ? 'NO' : 'UNKNOWN')
      setIncomeGenerating(ev.income_generating === true ? 'YES' : ev.income_generating === false ? 'NO' : 'UNKNOWN')
      setMseStatus(ev.micro_small_enterprise === true ? 'YES' : ev.micro_small_enterprise === false ? 'NO' : 'UNKNOWN')
      setUdyamCert(ev.udyam_certificate_present === true ? 'YES' : ev.udyam_certificate_present === false ? 'NO' : 'UNKNOWN')
      setGemPoDoc(ev.gem_po_document === true ? 'YES' : ev.gem_po_document === false ? 'NO' : 'UNKNOWN')
      setRelMonths(ev.supplier_relationship_months !== null && ev.supplier_relationship_months !== undefined ? String(ev.supplier_relationship_months) : '')
      setOnTimeRatio(ev.supplier_on_time_ratio !== null && ev.supplier_on_time_ratio !== undefined ? String(ev.supplier_on_time_ratio) : '')
      setExtensionStatus((ev.supplier_extension_status as 'UNKNOWN' | 'PROPOSED' | 'CONFIRMED') || 'UNKNOWN')
      setEvidenceRef(ev.evidence_ref || '')
    }
  }, [evidenceQuery.data])

  const saveEvidenceMutation = useMutation({
    mutationFn: (payload: FinancingEvidencePayload) => koshApi.saveFinancingEvidence(activeSellerId!, payload),
    onSuccess: () => {
      setSaveSuccess('Evidence saved successfully. Financing options re-evaluated.')
      qc.invalidateQueries({ queryKey: ['kosh', 'financing-evidence', activeSellerId] })
      qc.invalidateQueries({ queryKey: ['kosh', 'financing', activeSellerId] })
      qc.invalidateQueries({ queryKey: ['kosh', 'plan', activeSellerId] })
      qc.invalidateQueries({ queryKey: ['kosh', 'safety-curve', activeSellerId] })
    },
  })

  const handleSaveEvidence = (e: React.FormEvent) => {
    e.preventDefault()
    setSaveSuccess(null)
    const payload: FinancingEvidencePayload = {
      non_corporate: nonCorporate === 'YES' ? true : nonCorporate === 'NO' ? false : null,
      non_farm: nonFarm === 'YES' ? true : nonFarm === 'NO' ? false : null,
      income_generating: incomeGenerating === 'YES' ? true : incomeGenerating === 'NO' ? false : null,
      micro_small_enterprise: mseStatus === 'YES' ? true : mseStatus === 'NO' ? false : null,
      udyam_certificate_present: udyamCert === 'YES' ? true : udyamCert === 'NO' ? false : null,
      gem_po_document: gemPoDoc === 'YES' ? true : gemPoDoc === 'NO' ? false : null,
      supplier_relationship_months: relMonths.trim() !== '' ? parseInt(relMonths, 10) : null,
      supplier_on_time_ratio: onTimeRatio.trim() !== '' ? parseFloat(onTimeRatio) : null,
      supplier_extension_status: extensionStatus,
      evidence_ref: evidenceRef.trim() || undefined,
    }
    saveEvidenceMutation.mutate(payload)
  }

  const handleApplyFixture = (fixtureId: string) => {
    setSelectedFixture(fixtureId)
    setSaveSuccess(null)
    if (!fixtureId) return
    saveEvidenceMutation.mutate({ apply_fixture: fixtureId })
  }

  if (options.isLoading) return <PageLoader />
  if (options.isError)
    return (
      <section>
        <h2>Financing plan</h2>
        <ErrorAlert message="Financing options have not been evaluated." />
        <button onClick={() => evaluate.mutate()}>Evaluate options</button>
      </section>
    )

  const graph = (plan.data?.before_probabilities ?? []).map((before, i) => ({
    week: i + 1,
    before,
    after: plan.data?.after_probabilities[i],
  }))
  const saving = plan.data ? plan.data.baseline_cost_paise - plan.data.total_cost_paise : 0
  const isOwner = evidenceQuery.data?.role === 'OWNER'

  return (
    <section aria-label="Financing plan" className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">Financing options</h2>
        <button className="rounded bg-blue-700 px-3 py-2 text-white font-medium hover:bg-blue-800" onClick={() => propose.mutate()}>
          Build plan
        </button>
      </div>
      <p className="rounded bg-blue-50 p-3 text-sm text-blue-900">
        All options shown, including ones you don't qualify for. Sorted by effective annual cost; no provider pays for placement.
      </p>

      {/* Safety vs cost */}
      <div className="rounded border bg-white p-4 space-y-3">
        <label className="block text-sm font-medium">
          Plan safety target{' '}
          <select aria-label="Plan safety target" value={target} onChange={(e) => setTarget(e.target.value)} className="ml-2 rounded border px-2 py-1 text-sm">
            {['0.40', '0.30', '0.20', '0.10'].map((value) => (
              <option key={value} value={value}>
                {Number(value) * 100}%
              </option>
            ))}
          </select>
        </label>
        <h3 className="text-base font-semibold">Safety vs cost</h3>
        {curve.isLoading ? (
          <p>Computing same-seed plans...</p>
        ) : curve.isError ? (
          <p>Evaluate the latest forecast to see the safety curve.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="py-1">Target probability</th>
                <th className="py-1">Cost</th>
                <th className="py-1">After probability</th>
                <th className="py-1">Result</th>
              </tr>
            </thead>
            <tbody>
              {curve.data?.items.map((item) => (
                <tr key={item.target_probability} className="border-b">
                  <td className="py-1">{Number(item.target_probability) * 100}%</td>
                  <td className="py-1">{formatPaiseINR(item.total_cost_paise)}</td>
                  <td className="py-1">{(item.alert_week_probability * 100).toFixed(1)}%</td>
                  <td className="py-1">{item.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Financing Options Table */}
      <div className="overflow-x-auto rounded border bg-white p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2">Product</th>
              <th className="py-2">Status</th>
              <th className="py-2">Amount</th>
              <th className="py-2">Days</th>
              <th className="py-2">Absolute cost</th>
              <th className="py-2">Effective annual cost</th>
              <th className="py-2">Time to funds</th>
            </tr>
          </thead>
          <tbody>
            {options.data?.items.map((item, i) => (
              <tr key={`${item.product_id}-${i}`} className="border-b hover:bg-gray-50">
                <td className="py-2">
                  <span className="font-medium">{item.display_name}</span> {item.assumption && <small className="text-gray-500">(assumption)</small>}{' '}
                  {item.verify_before_relying && <small className="text-amber-600">(verify before relying)</small>}
                  <details className="mt-1 text-xs text-gray-600">
                    <summary className="cursor-pointer text-blue-600 hover:underline">Evidence and Why not?</summary>
                    <div className="mt-1 space-y-1 pl-2">
                      {item.reasons.map((r, j) => (
                        <p key={j}>
                          <span className="font-semibold">{r.reason_code}:</span> {r.reason} {r.product_clause?.quote}
                        </p>
                      ))}
                    </div>
                  </details>
                  {item.invoice_eligibility && (
                    <details className="mt-1 text-xs text-gray-600">
                      <summary className="cursor-pointer text-blue-600 hover:underline">
                        Per-invoice eligibility ({item.invoice_eligibility.filter((x) => x.eligible).length} eligible / {item.invoice_eligibility.length} open)
                      </summary>
                      <ul className="mt-1 list-disc pl-4 space-y-0.5">
                        {item.invoice_eligibility.map((invoice) => (
                          <li key={invoice.scope}>
                            {invoice.scope} {invoice.evidence.find((e) => e.invoice_number)?.invoice_number}: {invoice.status}{' '}
                            {invoice.reasons
                              .filter((r) => r.status !== 'MATCHED')
                              .map((r) => `${r.criterion}: ${r.reason}`)
                              .join('; ')}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
                <td className="py-2">
                  <span
                    className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${
                      item.status === 'MATCHED'
                        ? 'bg-green-100 text-green-800'
                        : item.status === 'NOT_MATCHED'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-amber-100 text-amber-800'
                    }`}
                    title={
                      item.status === 'MATCHED'
                        ? 'Recorded business facts meet catalogue criteria. This is not a loan sanction or lender approval.'
                        : undefined
                    }
                  >
                    {item.status === 'REVIEW_REQUIRED' ? 'NEEDS REVIEW' : item.status}
                  </span>
                  {item.status === 'MATCHED' && (
                    <small className="block text-[10px] text-gray-500">Meets criteria; not lender approval</small>
                  )}
                </td>
                <td className="py-2">{formatPaiseINR(item.amount_paise ?? item.max_amount_paise)}</td>
                <td className="py-2">
                  {item.days}
                  <small className="block text-xs text-gray-500">90-day quote basis</small>
                </td>
                <td className="py-2">
                  {item.cost_paise == null ? 'Pending evaluation' : formatPaiseINR(item.cost_paise)}
                  <small className="block text-xs text-gray-500">{item.cost_assumption}</small>
                </td>
                <td className="py-2">{item.effective_annual_rate == null ? 'Relationship risk' : `${(Number(item.effective_annual_rate) * 100).toFixed(1)}%`}</td>
                <td className="py-2">{item.arrival_business_days} business days</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Owner Financing Eligibility Evidence Workflow */}
      <section aria-label="Financing eligibility evidence" className="rounded border bg-white p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b pb-3">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Financing eligibility evidence</h3>
            <p className="text-xs text-gray-600">
              Record business facts to verify eligibility against scheme criteria. MATCHED indicates recorded facts meet scheme criteria; it does not constitute lender approval, loan sanction, or guaranteed funding.
            </p>
          </div>
          {evidenceQuery.data?.as_of && (
            <span className="text-xs text-gray-500 self-start sm:self-auto bg-gray-100 px-2 py-1 rounded">
              As-of date: <strong>{evidenceQuery.data.as_of}</strong>
            </span>
          )}
        </div>

        {/* Missing Criteria Breakdown */}
        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-gray-800">Missing criteria across review options</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {evidenceQuery.data?.missing_criteria.map((prod) => (
              <div key={prod.product_id} className="rounded border p-3 bg-gray-50 text-xs space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-gray-900">{prod.display_name}</span>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      prod.product_support_status === 'IMPLEMENTED' ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'
                    }`}
                  >
                    {prod.product_support_status === 'IMPLEMENTED' ? 'Implemented rules' : 'Under revision'}
                  </span>
                </div>
                <ul className="space-y-1 pl-2">
                  {prod.criteria.map((c) => (
                    <li key={c.criterion} className="flex items-start justify-between gap-2">
                      <div>
                        <span className="font-medium text-gray-700">{c.label}</span>
                        <span className="block text-[11px] text-gray-500">Evidence needed: {c.evidence_required}</span>
                      </div>
                      <span
                        className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          c.status === 'CONFIRMED' || c.status === 'VERIFIED' || c.status === 'LINKED_DOCUMENT'
                            ? 'bg-green-100 text-green-700'
                            : c.status === 'PROPOSAL'
                            ? 'bg-blue-100 text-blue-700'
                            : c.status === 'UNSUPPORTED'
                            ? 'bg-purple-100 text-purple-700'
                            : c.status === 'DECLARATION_ONLY'
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        {c.status === 'DECLARATION_ONLY'
                          ? 'DECLARATION ONLY (NEEDS DOC)'
                          : c.status === 'NEEDS_DOCUMENTATION'
                          ? 'NEEDS DOCUMENTATION'
                          : c.status}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* Fictional Demonstration Fixture Selector */}
        <div className="rounded border border-blue-200 bg-blue-50/60 p-3 space-y-2">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <span className="text-xs font-semibold text-blue-950 uppercase tracking-wide">Fictional demonstration fixtures</span>
              <p className="text-xs text-blue-800">
                Test eligibility re-evaluations with labelled fictional test fixtures. Demonstrates outcomes without modifying real business profiles.
              </p>
            </div>
            <select
              aria-label="Select demonstration fixture"
              value={selectedFixture}
              onChange={(e) => handleApplyFixture(e.target.value)}
              disabled={!isOwner || saveEvidenceMutation.isPending}
              className="rounded border border-blue-300 bg-white px-2 py-1 text-xs text-gray-800 shadow-sm"
            >
              <option value="">-- Apply a demonstration fixture --</option>
              {evidenceQuery.data?.fixtures.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label} ({f.id})
                </option>
              ))}
            </select>
          </div>
          {selectedFixture && (
            <p className="text-xs text-blue-900 bg-white/70 p-2 rounded border border-blue-200">
              {evidenceQuery.data?.fixtures.find((f) => f.id === selectedFixture)?.description}
            </p>
          )}
        </div>

        {/* Evidence Capture Form */}
        <form onSubmit={handleSaveEvidence} className="space-y-4 pt-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Non-corporate */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-non-corporate">
                Non-corporate constitution (PMMY)
              </label>
              <select
                id="ev-non-corporate"
                aria-label="Non-corporate constitution"
                value={nonCorporate}
                onChange={(e) => setNonCorporate(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Proprietorship / Partnership / Non-corporate)</option>
                <option value="NO">No (Corporate entity / Private limited)</option>
              </select>
            </div>

            {/* Non-farm */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-non-farm">
                Non-farm activity (PMMY)
              </label>
              <select
                id="ev-non-farm"
                aria-label="Non-farm activity"
                value={nonFarm}
                onChange={(e) => setNonFarm(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Manufacturing / Trading / Services)</option>
                <option value="NO">No (Agricultural / Farming activity)</option>
              </select>
            </div>

            {/* Income-generating */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-income-generating">
                Income-generating purpose (PMMY)
              </label>
              <select
                id="ev-income-generating"
                aria-label="Income-generating purpose"
                value={incomeGenerating}
                onChange={(e) => setIncomeGenerating(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Commercial income-generating business)</option>
                <option value="NO">No (Personal / Non-commercial)</option>
              </select>
            </div>

            {/* Micro/Small enterprise */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-mse-status">
                Micro / Small enterprise status
              </label>
              <select
                id="ev-mse-status"
                aria-label="Micro or Small enterprise status"
                value={mseStatus}
                onChange={(e) => setMseStatus(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Micro or Small enterprise under MSMED Act)</option>
                <option value="NO">No (Medium / Large enterprise)</option>
              </select>
            </div>

            {/* Udyam Certificate */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-udyam-cert">
                Udyam Certificate present (CGTMSE)
              </label>
              <select
                id="ev-udyam-cert"
                aria-label="Udyam Certificate present"
                value={udyamCert}
                onChange={(e) => setUdyamCert(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Unrecorded</option>
                <option value="YES">Yes (Registration certificate document uploaded / verified)</option>
                <option value="NO">No (Not available — needs documentation)</option>
              </select>
            </div>

            {/* GeM PO Document */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-gem-po">
                GeM Purchase Order document (GeM Sahay)
              </label>
              <select
                id="ev-gem-po"
                aria-label="GeM Purchase Order document"
                value={gemPoDoc}
                onChange={(e) => setGemPoDoc(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Not provided</option>
                <option value="YES">Yes (GeM Purchase Order reference present)</option>
                <option value="NO">No (No GeM contract)</option>
              </select>
            </div>

            {/* Supplier Relationship Months */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-rel-months">
                Supplier relationship tenure (months, min 12)
              </label>
              <input
                id="ev-rel-months"
                aria-label="Supplier relationship tenure in months"
                type="number"
                min="0"
                max="240"
                placeholder="e.g. 18"
                value={relMonths}
                onChange={(e) => setRelMonths(e.target.value)}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              />
            </div>

            {/* Supplier On-time Ratio */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-ontime-ratio">
                Supplier on-time payment ratio (0.0 to 1.0, min 0.80)
              </label>
              <input
                id="ev-ontime-ratio"
                aria-label="Supplier on-time payment ratio"
                type="number"
                step="0.01"
                min="0"
                max="1"
                placeholder="e.g. 0.90"
                value={onTimeRatio}
                onChange={(e) => setOnTimeRatio(e.target.value)}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              />
            </div>

            {/* Supplier Extension Agreement Status */}
            <div className="space-y-1 sm:col-span-2">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-ext-status">
                Supplier extension agreement status
              </label>
              <select
                id="ev-ext-status"
                aria-label="Supplier extension agreement status"
                value={extensionStatus}
                onChange={(e) => setExtensionStatus(e.target.value as 'UNKNOWN' | 'PROPOSED' | 'CONFIRMED')}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              >
                <option value="UNKNOWN">Unknown / Not agreed</option>
                <option value="PROPOSED">Proposed extension (Unconfirmed request; payment dates remain unchanged)</option>
                <option value="CONFIRMED">Confirmed supplier agreement (Signed agreement on record)</option>
              </select>
              {extensionStatus === 'PROPOSED' && (
                <p className="text-[11px] text-blue-700 mt-1">
                  Note: A proposed extension is an unconfirmed request sent to the supplier. A proposal alone does not change payable due dates or create cash receipts.
                </p>
              )}
            </div>

            {/* Evidence Reference */}
            <div className="space-y-1 sm:col-span-2">
              <label className="block text-xs font-medium text-gray-700" htmlFor="ev-ref">
                Supporting evidence reference or note (max 160 chars)
              </label>
              <input
                id="ev-ref"
                aria-label="Supporting evidence reference or note"
                type="text"
                maxLength={160}
                placeholder="e.g. Udyam cert UDYAM-KA-03-0012345; Partnership deed clause 3"
                value={evidenceRef}
                onChange={(e) => setEvidenceRef(e.target.value)}
                disabled={!isOwner}
                className="w-full rounded border px-2 py-1.5 text-xs text-gray-800"
              />
            </div>
          </div>

          {/* Form Actions */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-2 border-t">
            <div className="text-xs text-gray-500">
              {!isOwner ? (
                <span className="text-amber-700">Only seller owner may record or revise financing eligibility evidence.</span>
              ) : (
                <span>Evidence changes are recorded in the append-only audit chain. Affected financing plans will be marked STALE.</span>
              )}
            </div>
            <button
              type="submit"
              disabled={!isOwner || saveEvidenceMutation.isPending}
              className="w-full sm:w-auto rounded bg-blue-700 px-4 py-2 text-xs font-medium text-white hover:bg-blue-800 disabled:opacity-50"
            >
              {saveEvidenceMutation.isPending ? 'Saving...' : 'Save evidence'}
            </button>
          </div>

          {saveSuccess && (
            <div className="rounded bg-green-50 p-2.5 text-xs text-green-800 border border-green-200" role="status">
              {saveSuccess}
            </div>
          )}
          {saveEvidenceMutation.isError && (
            <div className="rounded bg-red-50 p-2.5 text-xs text-red-800 border border-red-200" role="alert">
              Failed to save evidence. Please try again.
            </div>
          )}
        </form>
      </section>

      {/* Proposed Gap-closing Plan */}
      {plan.data ? (
        <div className="rounded border bg-white p-4 space-y-3">
          <h3 className="text-base font-semibold">Proposed gap-closing plan</h3>
          <p className="text-sm text-gray-700">{plan.data.why_this_plan}</p>
          <p className="text-sm font-medium">
            {plan.data.status === 'VALID'
              ? 'Same-seed forecast meets the chosen safety target and every horizon week is below the alert threshold'
              : plan.data.status === 'INSUFFICIENT'
              ? 'INSUFFICIENT: this plan does not meet the safety conditions; re-evaluate options'
              : 'Safety target not verified; build a new plan.'}
          </p>
          <ul className="list-disc pl-5 text-sm space-y-1">
            {plan.data.lines.map((line) => (
              <li key={line.id} id={`plan-line-${line.id}`}>
                <span className="font-semibold">{line.product_id}:</span> {formatPaiseINR(line.amount_paise)}, week {line.arrival_week},{' '}
                {line.days > 0 ? `${line.days} days (${line.funding_date} to ${line.repayment_date})` : 'timing only; no financing tenor'},{' '}
                {line.repayment_assumption}, cost {formatPaiseINR(line.cost_paise)}, {line.required_tier}
              </li>
            ))}
          </ul>
          <p className="text-sm font-semibold">Total {formatPaiseINR(plan.data.total_cost_paise)}</p>
          {plan.data.planning_details?.baseline_status === 'VALID' ? (
            <p className="text-sm text-gray-700">
              NBFC baseline {formatPaiseINR(plan.data.baseline_cost_paise)}; saving {formatPaiseINR(saving)} (
              {plan.data.baseline_cost_paise ? ((saving / plan.data.baseline_cost_paise) * 100).toFixed(0) : 0}%)
            </p>
          ) : (
            <p className="text-sm text-gray-600">NBFC baseline insufficient or not verified; savings unavailable.</p>
          )}
          <div className="h-48 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={graph}>
                <XAxis dataKey="week" />
                <YAxis />
                <Tooltip />
                <Line dataKey="before" stroke="#dc2626" strokeWidth={2} />
                <Line dataKey="after" stroke="#15803d" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-500">No proposed plan yet.</p>
      )}
    </section>
  )
}
