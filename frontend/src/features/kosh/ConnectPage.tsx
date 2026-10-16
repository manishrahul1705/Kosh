import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  UploadCloud,
  FileText,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Play,
  Trash2,
  FileCheck,
  Layers,
  Lock,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { Card } from '@/components/ui/Card'
import { formatEnumLabel } from '@/lib/koshLabels'

export const ConnectPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [kind, setKind] = useState('BOOKS_EXPORT')
  const [file, setFile] = useState<File | null>(null)

  const docs = useQuery({
    queryKey: ['kosh', 'documents', activeSellerId],
    queryFn: () => koshApi.documents(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const consents = useQuery({
    queryKey: ['kosh', 'consents', activeSellerId],
    queryFn: () => koshApi.consents(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const refresh = () => qc.invalidateQueries({ queryKey: ['kosh'] })

  const upload = useMutation({
    mutationFn: () => koshApi.uploadDocument(activeSellerId!, kind, file!),
    onSuccess: () => {
      setFile(null)
      refresh()
    },
  })

  const create = () =>
    koshApi
      .createConsent(activeSellerId!, {
        purpose: 'Cash ledger intake',
        data_types: ['BANK_STATEMENT', 'SALES_INVOICES', 'PURCHASE_BILLS', 'BOOKS_EXPORT'],
        data_from: '2024-01-01',
        data_to: '2027-12-31',
        expires_at: new Date(Date.now() + 365 * 86400000).toISOString(),
      })
      .then(refresh)

  if (docs.isLoading || consents.isLoading) return <PageLoader />

  const processedCount = Array.isArray(docs.data) ? docs.data.filter((d) => d.status === 'PROCESSED').length : 0
  const reviewCount = Array.isArray(docs.data) ? docs.data.filter((d) => d.status === 'REVIEW').length : 0
  const activeConsentsCount = Array.isArray(consents.data) ? consents.data.filter((c) => c.status === 'ACTIVE').length : 0

  return (
    <section aria-label="Connect" className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200 pb-4">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-8 bg-gradient-to-b from-primary-500 to-primary-600 rounded-full shadow-xs shrink-0" />
          <div>
            <h2 className="text-xl font-bold text-metal-900 tracking-tight">Connect & Ingest Documents</h2>
            <p className="text-xs sm:text-sm text-metal-500 mt-0.5">
              Secure private document intake for cash forecasting, ledger reconciliation, and financing verification.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-2xs">
            <Lock size={12} className="text-emerald-600" />
            End-to-End Audited
          </span>
        </div>
      </div>

      {(docs.isError || consents.isError) && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-700">
          Failed to load documents or consent records.
        </div>
      )}

      {/* KPI Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="stat-card">
          <div className="flex items-center justify-between mb-2">
            <span className="stat-label">Active Consents</span>
            <div className="bg-emerald-50 text-emerald-600 p-2 rounded-lg">
              <ShieldCheck size={18} />
            </div>
          </div>
          <p className="stat-value text-emerald-700">{activeConsentsCount}</p>
          <p className="text-[11px] text-metal-400 mt-1">Legally binding scope</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-2">
            <span className="stat-label">Total Ingested</span>
            <div className="bg-metal-100 text-metal-700 p-2 rounded-lg">
              <Layers size={18} />
            </div>
          </div>
          <p className="stat-value text-metal-900">{docs.data?.length ?? 0}</p>
          <p className="text-[11px] text-metal-400 mt-1">Uploaded business files</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-2">
            <span className="stat-label">Processed Clean</span>
            <div className="bg-emerald-50 text-emerald-600 p-2 rounded-lg">
              <CheckCircle2 size={18} />
            </div>
          </div>
          <p className="stat-value text-emerald-600">{processedCount}</p>
          <p className="text-[11px] text-metal-400 mt-1">Parsed without anomaly</p>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between mb-2">
            <span className="stat-label">Quarantined / Review</span>
            <div className={reviewCount > 0 ? "bg-amber-50 text-amber-600 p-2 rounded-lg" : "bg-metal-100 text-metal-500 p-2 rounded-lg"}>
              <AlertTriangle size={18} />
            </div>
          </div>
          <p className={`stat-value ${reviewCount > 0 ? 'text-amber-600' : 'text-metal-900'}`}>{reviewCount}</p>
          <p className="text-[11px] text-metal-400 mt-1">Held for inspection</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Consent & Upload */}
        <div className="lg:col-span-1 space-y-6">
          {/* Consent Management */}
          <Card title="Consent Management" subtitle="Audited permissions required for data intake">
            <div className="space-y-3">
              {consents.data?.map((c) => (
                <div key={c.id} className="p-3.5 rounded-lg bg-metal-50/70 border border-metal-200 text-xs space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-metal-800" title={c.status}>
                      <span className="inline-flex items-center gap-1.5">
                        <CheckCircle2 size={13} className="text-emerald-600" />
                        {formatEnumLabel(c.status)}
                      </span>
                    </span>
                    {c.status === 'ACTIVE' && (
                      <button
                        className="inline-flex items-center gap-1 text-[11px] text-rose-600 font-semibold hover:text-rose-800 cursor-pointer"
                        onClick={() => koshApi.revokeConsent(activeSellerId!, c.id).then(refresh)}
                      >
                        <Trash2 size={11} />
                        Revoke
                      </button>
                    )}
                  </div>
                  <p className="text-metal-600 text-[11px] leading-relaxed">
                    <strong className="text-metal-700">Scope:</strong> {c.data_types.join(', ')}
                  </p>
                  <p className="text-metal-400 text-[10px]">Valid until {c.expires_at.slice(0, 10)}</p>
                </div>
              ))}

              {!consents.data?.length && (
                <div className="text-center p-5 rounded-lg bg-metal-50 border border-dashed border-metal-300 text-xs text-metal-500">
                  <p className="mb-3 font-medium">No active data intake consent recorded.</p>
                  <button className="btn-primary text-xs py-2 px-4 shadow-sm" onClick={create}>
                    Create intake consent
                  </button>
                </div>
              )}
            </div>
          </Card>

          {/* Upload Card */}
          <Card title="Upload Private Document" subtitle="Add ledger or statement documents">
            <div className="space-y-4">
              <div>
                <label className="label">Document Category</label>
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                  className="select text-xs"
                >
                  <option value="BOOKS_EXPORT">Accounting Export (Tally / Zoho / Books)</option>
                  <option value="BANK_STATEMENT">Bank Statement</option>
                  <option value="SALES_INVOICE">Sales Invoice</option>
                  <option value="PURCHASE_BILL">Purchase Bill</option>
                </select>
              </div>

              <div>
                <label className="label">Choose File</label>
                <input
                  aria-label="Private document"
                  type="file"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="w-full text-xs text-metal-600 file:mr-3 file:py-2 file:px-3.5 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-emerald-50 file:text-emerald-700 hover:file:bg-emerald-100 cursor-pointer border border-metal-200 rounded-lg p-1.5 bg-white"
                />
              </div>

              <button
                className="btn-primary w-full text-xs py-2.5 shadow-sm"
                disabled={!file || upload.isPending}
                onClick={() => upload.mutate()}
              >
                <UploadCloud size={15} />
                {upload.isPending ? 'Uploading...' : 'Upload Document'}
              </button>
            </div>
          </Card>
        </div>

        {/* Right Column: Ingested Documents List */}
        <div className="lg:col-span-2 space-y-4">
          <Card
            title="Ingested Documents"
            subtitle={`${docs.data?.length ?? 0} files recorded in tamper-evident store`}
            actions={
              <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-metal-100 text-metal-700 border border-metal-200">
                {docs.data?.length ?? 0} files
              </span>
            }
          >
            {docs.data?.length ? (
              <div className="space-y-3">
                {docs.data.map((d) => (
                  <div
                    key={d.id}
                    className="p-4 rounded-xl border border-metal-200 bg-white shadow-2xs hover:border-emerald-300 hover:shadow-xs transition-all space-y-2.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="p-2 rounded-lg bg-emerald-50 text-emerald-700 shrink-0">
                          <FileText size={17} />
                        </div>
                        <strong className="text-xs sm:text-sm font-bold text-metal-900 truncate">
                          {d.original_filename}
                        </strong>
                      </div>

                      <span
                        title={d.status}
                        className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-bold ${
                          d.status === 'REVIEW'
                            ? 'bg-amber-100 text-amber-800 border border-amber-300'
                            : d.status === 'PROCESSED'
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                            : 'bg-metal-100 text-metal-800 border border-metal-200'
                        }`}
                      >
                        {d.status === 'REVIEW' && <AlertTriangle size={12} />}
                        {d.status === 'PROCESSED' && <CheckCircle2 size={12} />}
                        {formatEnumLabel(d.status)}
                      </span>
                    </div>

                    {d.status_reason?.includes('INSTRUCTION_TEXT_DETECTED') && (
                      <div
                        role="alert"
                        className="flex items-center gap-2 text-xs font-semibold text-rose-800 bg-rose-50 p-3 rounded-lg border border-rose-200"
                      >
                        <AlertTriangle size={15} className="shrink-0 text-rose-600" />
                        <span>⚠ Suspicious instruction-like text detected. Quarantined for review and excluded from cash forecast.</span>
                      </div>
                    )}

                    <div className="flex items-center justify-between pt-2 border-t border-metal-100 text-xs">
                      <span className="text-metal-400 text-[11px] font-mono">ID #{d.id}</span>
                      <button
                        className="inline-flex items-center gap-1.5 text-xs text-emerald-700 font-bold hover:text-emerald-900 transition-colors cursor-pointer"
                        onClick={() => koshApi.processDocument(activeSellerId!, d.id).then(refresh)}
                      >
                        <Play size={12} />
                        Process document
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-12 text-center text-xs text-metal-500 space-y-3 border border-dashed border-metal-300 rounded-xl bg-metal-50/50">
                <FileText size={36} className="mx-auto text-metal-300" />
                <p className="font-bold text-sm text-metal-700">No documents uploaded yet.</p>
                <p className="text-metal-500 max-w-sm mx-auto leading-relaxed">
                  Upload sales register CSV, purchase register CSV, bank statement JSON, or invoice PDFs to populate the financial ledger.
                </p>
              </div>
            )}
          </Card>
        </div>
      </div>
    </section>
  )
}
export default ConnectPage
