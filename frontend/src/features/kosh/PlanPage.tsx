import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useSeller } from '@/app/SellerContext'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { koshApi, FinancingEvidencePayload } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
import { formatEnumLabel } from '@/lib/koshLabels'

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
    week: `W${i + 1}`,
    before: Math.round(before * 10000) / 100,
    after: plan.data?.after_probabilities[i] !== undefined ? Math.round(plan.data.after_probabilities[i] * 10000) / 100 : undefined,
  }))
  const saving = plan.data ? plan.data.baseline_cost_paise - plan.data.total_cost_paise : 0
  const isOwner = evidenceQuery.data?.role === 'OWNER'


  return (
    <section aria-label="Financing plan" className="space-y-6">
      <SandboxBanner />

      {/* Header & Propose Action */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Financing options</h2>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Objective, catalogue-wide criteria matching sorted strictly by effective annual cost.
          </p>
        </div>
        <button
          className="btn-primary self-start sm:self-auto"
          onClick={() => propose.mutate()}
        >
          Build plan
        </button>
      </div>

      <div className="p-3.5 rounded-xl bg-blue-50/80 border border-blue-200/80 text-xs text-blue-950 font-medium">
        All options shown, including ones you don't qualify for. Sorted by effective annual cost; no provider pays for placement.
      </div>

      {/* Safety vs cost */}
      <div className="card p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-base font-bold text-slate-900 tracking-tight">Safety vs cost</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Trade-off curve across same-seed simulated paths under varying safety targets.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200">
            <span>Plan safety target</span>
            <select
              aria-label="Plan safety target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-bold text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {['0.40', '0.30', '0.20', '0.10'].map((value) => (
                <option key={value} value={value}>
                  {Number(value) * 100}%
                </option>
              ))}
            </select>
          </label>
        </div>

        {curve.isLoading ? (
          <p className="text-xs text-slate-500 py-3">Computing same-seed plans...</p>
        ) : curve.isError ? (
          <p className="text-xs text-slate-500 py-3">Evaluate the latest forecast to see the safety curve.</p>
        ) : (
          <div className="table-container border-0 shadow-none">
            <table>
              <thead>
                <tr>
                  <th>Target probability</th>
                  <th>Cost</th>
                  <th>After probability</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {curve.data?.items.map((item) => (
                  <tr key={item.target_probability} className="hover:bg-slate-50/70">
                    <td className="font-bold text-slate-900">{Number(item.target_probability) * 100}%</td>
                    <td className="font-semibold text-slate-900">{formatPaiseINR(item.total_cost_paise)}</td>
                    <td className="text-slate-700">{(item.alert_week_probability * 100).toFixed(1)}%</td>
                    <td>
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          item.status === 'VALID'
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {item.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Financing Options Table */}
      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-bold text-sm text-slate-900 tracking-tight">Financing Options Catalogue</h3>
          <span className="text-xs text-slate-500">{options.data?.items.length ?? 0} options available</span>
        </div>
        <div className="table-container border-0 shadow-none rounded-none">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>Status</th>
                <th>Amount</th>
                <th>Days</th>
                <th>Absolute cost</th>
                <th>Effective annual cost</th>
                <th>Time to funds</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {options.data?.items.map((item, i) => (
                <tr key={`${item.product_id}-${i}`} className="hover:bg-slate-50/70">
                  <td className="py-3">
                    <div className="font-bold text-slate-900">{item.display_name}</div>
                    <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                      {item.assumption && (
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-500 font-medium">
                          (assumption)
                        </span>
                      )}
                      {item.verify_before_relying && (
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-100 text-amber-800 font-semibold">
                          (verify before relying)
                        </span>
                      )}
                    </div>
                    <details className="mt-1.5 text-xs text-slate-600">
                      <summary className="cursor-pointer font-semibold text-blue-600 hover:underline">
                        Evidence and Why not?
                      </summary>
                      <div className="mt-1 space-y-1 pl-2 border-l-2 border-slate-200">
                        {item.reasons.map((r, j) => (
                          <p key={j} className="text-[11px] text-slate-700">
                            <span className="font-bold text-slate-900">{r.reason_code}:</span> {r.reason}{' '}
                            {r.product_clause?.quote && (
                              <span className="italic text-slate-500">"{r.product_clause.quote}"</span>
                            )}
                          </p>
                        ))}
                      </div>
                    </details>
                    {item.invoice_eligibility && (
                      <details className="mt-1.5 text-xs text-slate-600">
                        <summary className="cursor-pointer font-semibold text-blue-600 hover:underline">
                          Per-invoice eligibility ({item.invoice_eligibility.filter((x) => x.eligible).length} eligible / {item.invoice_eligibility.length} open)
                        </summary>
                        <ul className="mt-1 list-disc pl-4 space-y-0.5 text-[11px] text-slate-700">
                          {item.invoice_eligibility.map((invoice) => (
                            <li key={invoice.scope}>
                              <span className="font-medium text-slate-900">{invoice.scope}</span>{' '}
                              {invoice.evidence.find((e) => e.invoice_number)?.invoice_number}:{' '}
                              <span className="font-semibold">{invoice.status}</span>{' '}
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
                  <td>
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold ${
                        item.status === 'MATCHED'
                          ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                          : item.status === 'NOT_MATCHED'
                          ? 'bg-rose-100 text-rose-800 border border-rose-200'
                          : 'bg-amber-100 text-amber-800 border border-amber-200'
                      }`}
                      title={
                        item.status === 'MATCHED'
                          ? `${item.status}: Recorded business facts meet catalogue criteria. This is not a loan sanction or lender approval.`
                          : item.status
                      }
                    >
                      {formatEnumLabel(item.status)}
                    </span>
                    {item.status === 'MATCHED' && (
                      <small className="block text-[10px] text-slate-500 mt-0.5">Meets criteria; not lender approval</small>
                    )}
                  </td>
                  <td className="font-semibold text-slate-900">
                    {formatPaiseINR(item.amount_paise ?? item.max_amount_paise)}
                  </td>
                  <td>
                    <span className="font-medium text-slate-900">{item.days}</span>
                    <small className="block text-[10px] text-slate-400">90-day quote basis</small>
                  </td>
                  <td>
                    <span className="font-semibold text-slate-900">
                      {item.cost_paise == null ? 'Pending evaluation' : formatPaiseINR(item.cost_paise)}
                    </span>
                    <small className="block text-[10px] text-slate-400">{item.cost_assumption}</small>
                  </td>
                  <td className="font-medium text-slate-900">
                    {item.effective_annual_rate == null ? 'Relationship risk' : `${(Number(item.effective_annual_rate) * 100).toFixed(1)}%`}
                  </td>
                  <td className="text-slate-700">{item.arrival_business_days} business days</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Owner Financing Eligibility Evidence Workflow */}
      <section aria-label="Financing eligibility evidence" className="card p-5 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-base font-bold text-slate-900 tracking-tight">Financing eligibility evidence</h3>
            <p className="text-xs text-slate-600 mt-0.5">
              Record business facts to verify eligibility against scheme criteria. MATCHED indicates recorded facts meet scheme criteria; it does not constitute lender approval, loan sanction, or guaranteed funding.
            </p>
          </div>
          {evidenceQuery.data?.as_of && (
            <span className="text-xs text-slate-600 self-start sm:self-auto bg-slate-100 px-2.5 py-1 rounded-lg border border-slate-200">
              As-of date: <strong>{evidenceQuery.data.as_of}</strong>
            </span>
          )}
        </div>

        {/* Missing Criteria Breakdown */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">Missing criteria across review options</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {evidenceQuery.data?.missing_criteria.map((prod) => (
              <div key={prod.product_id} className="rounded-xl border border-slate-200/80 p-3.5 bg-slate-50/70 text-xs space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900">{prod.display_name}</span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                      prod.product_support_status === 'IMPLEMENTED' ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'
                    }`}
                  >
                    {prod.product_support_status === 'IMPLEMENTED' ? 'Implemented rules' : 'Under revision'}
                  </span>
                </div>
                <ul className="space-y-1.5 pl-1">
                  {prod.criteria.map((c) => (
                    <li key={c.criterion} className="flex items-start justify-between gap-2">
                      <div>
                        <span className="font-semibold text-slate-800">{c.label}</span>
                        <span className="block text-[11px] text-slate-500">Evidence needed: {c.evidence_required}</span>
                      </div>
                      <span
                        className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          c.status === 'CONFIRMED' || c.status === 'VERIFIED' || c.status === 'LINKED_DOCUMENT'
                            ? 'bg-emerald-100 text-emerald-800'
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
        <div className="rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50/90 to-indigo-50/50 p-4 space-y-2.5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <span className="text-xs font-bold text-blue-950 uppercase tracking-wider">Fictional demonstration fixtures</span>
              <p className="text-xs text-blue-800 mt-0.5">
                Test eligibility re-evaluations with labelled fictional test fixtures. Demonstrates outcomes without modifying real business profiles.
              </p>
            </div>
            <select
              aria-label="Select demonstration fixture"
              value={selectedFixture}
              onChange={(e) => handleApplyFixture(e.target.value)}
              disabled={!isOwner || saveEvidenceMutation.isPending}
              className="rounded-lg border border-blue-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-800 shadow-xs focus:ring-2 focus:ring-blue-500"
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
            <p className="text-xs text-blue-900 bg-white/80 p-2.5 rounded-lg border border-blue-200 font-medium">
              {evidenceQuery.data?.fixtures.find((f) => f.id === selectedFixture)?.description}
            </p>
          )}
        </div>

        {/* Evidence Capture Form */}
        <form onSubmit={handleSaveEvidence} className="space-y-4 pt-1">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Non-corporate */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-non-corporate">
                Non-corporate constitution (PMMY)
              </label>
              <select
                id="ev-non-corporate"
                aria-label="Non-corporate constitution"
                value={nonCorporate}
                onChange={(e) => setNonCorporate(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="select text-xs"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Proprietorship / Partnership / Non-corporate)</option>
                <option value="NO">No (Corporate entity / Private limited)</option>
              </select>
            </div>

            {/* Non-farm */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-non-farm">
                Non-farm activity (PMMY)
              </label>
              <select
                id="ev-non-farm"
                aria-label="Non-farm activity"
                value={nonFarm}
                onChange={(e) => setNonFarm(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="select text-xs"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Manufacturing / Trading / Services)</option>
                <option value="NO">No (Agricultural / Farming activity)</option>
              </select>
            </div>

            {/* Income-generating */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-income-generating">
                Income-generating purpose (PMMY)
              </label>
              <select
                id="ev-income-generating"
                aria-label="Income-generating purpose"
                value={incomeGenerating}
                onChange={(e) => setIncomeGenerating(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="select text-xs"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Commercial income-generating business)</option>
                <option value="NO">No (Personal / Non-commercial)</option>
              </select>
            </div>

            {/* Micro/Small enterprise */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-mse-status">
                Micro / Small enterprise status
              </label>
              <select
                id="ev-mse-status"
                aria-label="Micro or Small enterprise status"
                value={mseStatus}
                onChange={(e) => setMseStatus(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="select text-xs"
              >
                <option value="UNKNOWN">Unknown / Not recorded</option>
                <option value="YES">Yes (Micro or Small enterprise under MSMED Act)</option>
                <option value="NO">No (Medium / Large enterprise)</option>
              </select>
            </div>

            {/* Udyam Certificate */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-udyam-cert">
                Udyam Certificate present (CGTMSE)
              </label>
              <select
                id="ev-udyam-cert"
                aria-label="Udyam Certificate present"
                value={udyamCert}
                onChange={(e) => setUdyamCert(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="select text-xs"
              >
                <option value="UNKNOWN">Unknown / Unrecorded</option>
                <option value="YES">Yes (Registration certificate document uploaded / verified)</option>
                <option value="NO">No (Not available — needs documentation)</option>
              </select>
            </div>

            {/* GeM PO Document */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-gem-po">
                GeM Purchase Order document (GeM Sahay)
              </label>
              <select
                id="ev-gem-po"
                aria-label="GeM Purchase Order document"
                value={gemPoDoc}
                onChange={(e) => setGemPoDoc(e.target.value as 'UNKNOWN' | 'YES' | 'NO')}
                disabled={!isOwner}
                className="select text-xs"
              >
                <option value="UNKNOWN">Unknown / Not provided</option>
                <option value="YES">Yes (GeM Purchase Order reference present)</option>
                <option value="NO">No (No GeM contract)</option>
              </select>
            </div>

            {/* Supplier Relationship Months */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-rel-months">
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
                className="input text-xs"
              />
            </div>

            {/* Supplier On-time Ratio */}
            <div className="space-y-1">
              <label className="label" htmlFor="ev-ontime-ratio">
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
                className="input text-xs"
              />
            </div>

            {/* Supplier Extension Agreement Status */}
            <div className="space-y-1 sm:col-span-2">
              <label className="label" htmlFor="ev-ext-status">
                Supplier extension agreement status
              </label>
              <select
                id="ev-ext-status"
                aria-label="Supplier extension agreement status"
                value={extensionStatus}
                onChange={(e) => setExtensionStatus(e.target.value as 'UNKNOWN' | 'PROPOSED' | 'CONFIRMED')}
                disabled={!isOwner}
                className="select text-xs"
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
              <label className="label" htmlFor="ev-ref">
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
                className="input text-xs"
              />
            </div>
          </div>

          {/* Form Actions */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-slate-100">
            <div className="text-xs text-slate-500">
              {!isOwner ? (
                <span className="text-amber-700 font-semibold">Only seller owner may record or revise financing eligibility evidence.</span>
              ) : (
                <span>Evidence changes are recorded in the append-only audit chain. Affected financing plans will be marked STALE.</span>
              )}
            </div>
            <button
              type="submit"
              disabled={!isOwner || saveEvidenceMutation.isPending}
              className="btn-primary text-xs py-2 px-4 w-full sm:w-auto"
            >
              {saveEvidenceMutation.isPending ? 'Saving...' : 'Save evidence'}
            </button>
          </div>

          {saveSuccess && (
            <div className="rounded-xl bg-emerald-50 p-3 text-xs text-emerald-800 border border-emerald-200 font-medium" role="status">
              {saveSuccess}
            </div>
          )}
          {saveEvidenceMutation.isError && (
            <div className="rounded-xl bg-rose-50 p-3 text-xs text-rose-800 border border-rose-200 font-medium" role="alert">
              Failed to save evidence. Please try again.
            </div>
          )}
        </form>
      </section>

      {/* Proposed Gap-closing Plan */}
      {plan.data ? (
        <div className="card p-5 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
            <div>
              <h3 className="text-base font-bold text-slate-900 tracking-tight">Proposed gap-closing plan</h3>
              <p className="text-xs text-slate-600 mt-0.5">
                Validity check against the target probability ({Number(plan.data.target_probability) * 100}%) across {plan.data.planning_details?.target_scope === 'ALERT_WEEK' ? 'Alert Week' : 'All Horizon Weeks'} is strictly verified using the <strong>Binding financing plan</strong>.
              </p>
            </div>
            <span
              className={`px-3 py-1 rounded-full text-xs font-bold self-start sm:self-auto ${
                plan.data.status === 'VALID'
                  ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                  : 'bg-rose-100 text-rose-800 border border-rose-200'
              }`}
            >
              {plan.data.status === 'VALID' ? 'PLAN VALID (BINDING)' : plan.data.status}
            </span>
          </div>

          <div className="p-3.5 rounded-lg bg-slate-50 border border-slate-200 text-xs font-medium text-slate-800 space-y-1">
            <p className="font-semibold">{plan.data.why_this_plan}</p>
            <p className="text-[11px] text-slate-500">
              Matched means recorded facts meet catalogue criteria; matching is not lender approval, loan sanction or guaranteed funding. Sandbox execution is not real funding. The binding plan excludes both uncertain collections and supplier payment extensions; expected collections remain separate.
            </p>
          </div>

          {/* Dual plan metrics: Binding vs Expected */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Binding Financing Plan Card */}
            <div className="rounded-xl border border-blue-200 bg-gradient-to-br from-blue-50/70 to-indigo-50/40 p-4 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-blue-950">Binding financing plan</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 font-bold border border-blue-200">
                  Cash-posting levers only
                </span>
              </div>
              <p className="text-xs text-slate-600">
                Only levers that post cash on execution (e.g. TReDS discounting, Bank OD). Target validity is verified strictly against this binding financing allocation.
              </p>
              <div className="pt-2 flex items-baseline justify-between text-xs border-t border-blue-100">
                <span className="text-slate-600">Binding plan cost:</span>
                <span className="text-base font-bold text-slate-900">
                  {formatPaiseINR(plan.data.guaranteed_plan?.total_cost_paise ?? plan.data.planning_details?.guaranteed_total_cost_paise ?? plan.data.total_cost_paise)}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-slate-600">Alert week probability:</span>
                <span className="font-bold text-slate-800">
                  {plan.data.guaranteed_plan
                    ? `${(plan.data.guaranteed_plan.alert_week_probability * 100).toFixed(1)}%`
                    : 'Verified <= 20%'}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-slate-600">Verification status:</span>
                <span className={`font-bold ${plan.data.planning_details?.guaranteed_status === 'VALID' || plan.data.status === 'VALID' ? 'text-emerald-700' : 'text-rose-700'}`}>
                  {plan.data.planning_details?.guaranteed_status ?? plan.data.status}
                </span>
              </div>
            </div>

            {/* Expected with Collections Card */}
            <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50/70 to-orange-50/40 p-4 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-amber-950">Expected with collections</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-bold border border-amber-200">
                  Uncertain cash timing
                </span>
              </div>
              <p className="text-xs text-slate-600">
                Includes collections reminder pushes. Reminders cost zero monetary fees but cash receipt remains uncertain until buyer pays.
              </p>
              <div className="pt-2 flex items-baseline justify-between text-xs border-t border-amber-100">
                <span className="text-slate-600">Expected cost:</span>
                <span className="text-base font-bold text-slate-900">
                  {formatPaiseINR(plan.data.expected_plan?.total_cost_paise ?? plan.data.planning_details?.expected_total_cost_paise ?? plan.data.total_cost_paise)}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-slate-600">Alert week probability:</span>
                <span className="font-bold text-slate-800">
                  {plan.data.expected_plan
                    ? `${(plan.data.expected_plan.alert_week_probability * 100).toFixed(1)}%`
                    : `${(plan.data.after_probabilities[plan.data.after_probabilities.length > 5 ? 5 : 0] * 100).toFixed(1)}%`}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-slate-600">Levers status:</span>
                <span className="font-bold text-amber-800">
                  {plan.data.expected_plan?.status ?? 'INCLUDED WITH COLLECTIONS'}
                </span>
              </div>
            </div>
          </div>

          <p className="text-xs sm:text-sm font-semibold text-slate-800 p-3 rounded-lg bg-slate-50 border border-slate-200">
            {plan.data.status === 'VALID'
              ? 'Same-seed forecast meets the chosen safety target and every horizon week is below the alert threshold'
              : plan.data.status === 'INSUFFICIENT'
              ? 'INSUFFICIENT: this plan does not meet the safety conditions; re-evaluate options'
              : 'Safety target not verified; build a new plan.'}
          </p>

          <div className="space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Executed Plan Levers</h4>
            <ul className="list-disc pl-5 text-xs text-slate-700 space-y-1.5">
              {plan.data.lines.map((line) => (
                <li key={line.id} id={`plan-line-${line.id}`} className="leading-relaxed">
                  <span className="font-bold text-slate-900">{line.product_id}:</span> {formatPaiseINR(line.amount_paise)}, week {line.arrival_week},{' '}
                  {line.days > 0 ? `${line.days} days (${line.funding_date} to ${line.repayment_date})` : 'timing only; no financing tenor'},{' '}
                  {line.repayment_assumption}, cost {formatPaiseINR(line.cost_paise)}, <span className="font-semibold text-blue-700">{line.required_tier}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-100 border border-slate-200/90 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <p className="text-sm font-bold text-slate-900">Total {formatPaiseINR(plan.data.total_cost_paise)}</p>
            {plan.data.planning_details?.baseline_status === 'VALID' ? (
              <p className="text-xs text-slate-700 font-medium">
                NBFC baseline {formatPaiseINR(plan.data.baseline_cost_paise)}; saving <strong className="text-emerald-700">{formatPaiseINR(saving)}</strong> (
                {plan.data.baseline_cost_paise ? ((saving / plan.data.baseline_cost_paise) * 100).toFixed(0) : 0}%)
              </p>
            ) : (
              <p className="text-xs text-slate-600">NBFC baseline insufficient or not verified; savings unavailable.</p>
            )}
          </div>

          <div className="h-56 pt-2 space-y-2">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs text-slate-500 gap-1">
              <span className="font-semibold text-slate-700">Per-week probability below buffer (Target: {plan.data.planning_details?.target_scope ?? 'ALL_WEEKS'} &le; {Number(plan.data.target_probability) * 100}%)</span>
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5 font-medium"><span className="w-3 h-0.5 bg-rose-600 inline-block" /> Pre-intervention</span>
                <span className="flex items-center gap-1.5 font-medium"><span className="w-3 h-0.5 bg-emerald-700 inline-block" /> Post-plan</span>
              </div>
            </div>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={graph}>
                <XAxis dataKey="week" stroke="#64748b" fontSize={11} />
                <YAxis unit="%" domain={[0, 100]} stroke="#64748b" fontSize={11} />
                <Tooltip formatter={(value) => [`${value}%`]} />
                <Line name="Pre-intervention" dataKey="before" stroke="#dc2626" strokeWidth={2.5} dot={{ r: 3 }} />
                <Line name="Post-plan" dataKey="after" stroke="#15803d" strokeWidth={2.5} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <div className="card p-8 text-center text-xs text-slate-400">
          No proposed plan yet.
        </div>
      )}
    </section>
  )
}

