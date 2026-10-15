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
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
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

  const processedCount = docs.data?.filter((d) => d.status === 'PROCESSED').length ?? 0
  const reviewCount = docs.data?.filter((d) => d.status === 'REVIEW').length ?? 0

  return (
    <section aria-label="Connect" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-slate-200/80 pb-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Connect & Ingest Documents</h2>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Secure private document storage and parsing for cash forecasting and financing verification.
          </p>
        </div>
      </div>

      {(docs.isError || consents.isError) && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-700">
          Failed to load documents or consent records.
        </div>
      )}

      {/* KPI Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="stat-card">
          <p className="stat-label">Active Consents</p>
          <p className="stat-value text-blue-600">{consents.data?.filter((c) => c.status === 'ACTIVE').length ?? 0}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Total Ingested</p>
          <p className="stat-value text-slate-900">{docs.data?.length ?? 0}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Processed Clean</p>
          <p className="stat-value text-emerald-600">{processedCount}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Quarantined / Review</p>
          <p className={`stat-value ${reviewCount > 0 ? 'text-amber-600' : 'text-slate-900'}`}>{reviewCount}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Consent & Upload */}
        <div className="lg:col-span-1 space-y-6">
          {/* Consent Management */}
          <div className="card p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <ShieldCheck size={18} className="text-blue-600" />
              <h3 className="font-bold text-sm text-slate-900 tracking-tight">Consent Management</h3>
            </div>

            <div className="space-y-3">
              {consents.data?.map((c) => (
                <div key={c.id} className="p-3 rounded-lg bg-slate-50 border border-slate-200/70 text-xs space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-800" title={c.status}>
                      <span className="inline-flex items-center gap-1">
                        <CheckCircle2 size={12} className="text-emerald-600" />
                        {formatEnumLabel(c.status)}
                      </span>
                    </span>
                    {c.status === 'ACTIVE' && (
                      <button
                        className="inline-flex items-center gap-1 text-[11px] text-rose-600 font-semibold hover:text-rose-800"
                        onClick={() => koshApi.revokeConsent(activeSellerId!, c.id).then(refresh)}
                      >
                        <Trash2 size={11} />
                        Revoke
                      </button>
                    )}
                  </div>
                  <p className="text-slate-600 text-[11px]">
                    <strong>Scope:</strong> {c.data_types.join(', ')}
                  </p>
                  <p className="text-slate-400 text-[10px]">Valid until {c.expires_at.slice(0, 10)}</p>
                </div>
              ))}

              {!consents.data?.length && (
                <div className="text-center p-4 rounded-lg bg-slate-50 border border-dashed border-slate-200 text-xs text-slate-500">
                  <p className="mb-2">No active data intake consent recorded.</p>
                  <button className="btn-primary text-xs py-1.5 px-3" onClick={create}>
                    Create intake consent
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Upload Card */}
          <div className="card p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <UploadCloud size={18} className="text-blue-600" />
              <h3 className="font-bold text-sm text-slate-900 tracking-tight">Upload Private Document</h3>
            </div>

            <div className="space-y-3">
              <div>
                <label className="label">Document Category</label>
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                  className="select text-xs"
                >
                  <option value="BOOKS_EXPORT">BOOKS_EXPORT</option>
                  <option value="BANK_STATEMENT">BANK_STATEMENT</option>
                  <option value="SALES_INVOICE">SALES_INVOICE</option>
                  <option value="PURCHASE_BILL">PURCHASE_BILL</option>
                </select>
              </div>

              <div>
                <label className="label">Choose File</label>
                <input
                  aria-label="Private document"
                  type="file"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="w-full text-xs text-slate-600 file:mr-2.5 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer"
                />
              </div>

              <button
                className="btn-primary w-full text-xs py-2"
                disabled={!file || upload.isPending}
                onClick={() => upload.mutate()}
              >
                <UploadCloud size={14} />
                {upload.isPending ? 'Uploading...' : 'Upload'}
              </button>
            </div>
          </div>
        </div>

        {/* Right Column: Ingested Documents List */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileCheck size={18} className="text-slate-700" />
              <h3 className="font-bold text-sm text-slate-900 tracking-tight">Ingested Documents</h3>
            </div>
            <span className="text-xs text-slate-500">{docs.data?.length ?? 0} files</span>
          </div>

          {docs.data?.length ? (
            <div className="space-y-3">
              {docs.data.map((d) => (
                <div
                  key={d.id}
                  className="card p-4 space-y-2 hover:border-slate-300 transition-colors"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="p-1.5 rounded-lg bg-blue-50 text-blue-600 shrink-0">
                        <FileText size={16} />
                      </div>
                      <strong className="text-xs sm:text-sm font-semibold text-slate-900 truncate">
                        {d.original_filename}
                      </strong>
                    </div>

                    <span
                      title={d.status}
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                        d.status === 'REVIEW'
                          ? 'bg-amber-100 text-amber-800 border border-amber-200'
                          : d.status === 'PROCESSED'
                          ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                          : 'bg-slate-100 text-slate-800 border border-slate-200'
                      }`}
                    >
                      {d.status === 'REVIEW' && <AlertTriangle size={11} />}
                      {d.status === 'PROCESSED' && <CheckCircle2 size={11} />}
                      {formatEnumLabel(d.status)}
                    </span>
                  </div>

                  {d.status_reason?.includes('INSTRUCTION_TEXT_DETECTED') && (
                    <div
                      role="alert"
                      className="flex items-center gap-2 text-xs font-semibold text-rose-800 bg-rose-50 p-2.5 rounded-lg border border-rose-200"
                    >
                      <AlertTriangle size={14} className="shrink-0 text-rose-600" />
                      <span>⚠ Instruction-like payment text detected. Quarantined in REVIEW.</span>
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-1 border-t border-slate-100 text-xs">
                    <span className="text-slate-400 text-[11px]">ID #{d.id}</span>
                    <button
                      className="inline-flex items-center gap-1 text-xs text-blue-600 font-semibold hover:text-blue-800"
                      onClick={() => koshApi.processDocument(activeSellerId!, d.id).then(refresh)}
                    >
                      <Play size={11} />
                      Process document
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="card p-10 text-center text-xs text-slate-500 space-y-2 border-dashed">
              <FileText size={32} className="mx-auto text-slate-300" />
              <p className="font-semibold text-slate-700">No documents uploaded yet.</p>
              <p className="text-slate-400 max-w-sm mx-auto">
                Upload sales register CSV, purchase register CSV, bank statement JSON, or invoice PDFs to populate the ledger.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

