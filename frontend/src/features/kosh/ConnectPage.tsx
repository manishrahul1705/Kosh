import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
    onSuccess: refresh,
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

  return (
    <section aria-label="Connect" className="space-y-4">
      <SandboxBanner />
      <h2 className="text-xl font-semibold">Connect & Ingest Documents</h2>
      <p className="text-sm text-gray-600">
        Secure private document storage and parsing for cash forecasting and financing verification.
      </p>

      {(docs.isError || consents.isError) && (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load documents or consent records.
        </div>
      )}

      <div className="rounded border bg-white p-4 space-y-2">
        <h3 className="font-semibold text-base text-gray-900">Consent Management</h3>
        {consents.data?.map((c) => (
          <div key={c.id} className="flex flex-wrap items-center justify-between text-sm py-1 border-b last:border-b-0">
            <span>
              <strong className="font-semibold text-gray-800" title={c.status}>
                {formatEnumLabel(c.status)}
              </strong>
              : {c.data_types.join(', ')} until {c.expires_at.slice(0, 10)}
            </span>
            {c.status === 'ACTIVE' && (
              <button className="text-xs text-red-600 underline font-medium hover:text-red-800" onClick={() => koshApi.revokeConsent(activeSellerId!, c.id).then(refresh)}>
                Revoke
              </button>
            )}
          </div>
        ))}
        {!consents.data?.length && (
          <button className="rounded border border-blue-600 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50" onClick={create}>
            Create intake consent
          </button>
        )}
      </div>

      <div className="rounded border bg-white p-4 space-y-3">
        <h3 className="font-semibold text-base text-gray-900">Upload Private Document</h3>
        <div className="flex flex-wrap items-center gap-3">
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded border px-2 py-1.5 text-sm">
            <option>BOOKS_EXPORT</option>
            <option>BANK_STATEMENT</option>
            <option>SALES_INVOICE</option>
            <option>PURCHASE_BILL</option>
          </select>
          <input aria-label="Private document" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm text-gray-600" />
          <button
            className="rounded bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
            disabled={!file || upload.isPending}
            onClick={() => upload.mutate()}
          >
            Upload
          </button>
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="font-semibold text-base text-gray-900">Ingested Documents</h3>
        {docs.data?.length ? (
          docs.data.map((d) => (
            <div className="rounded border bg-white p-3 space-y-1" key={d.id}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong className="text-sm font-medium text-gray-900">{d.original_filename}</strong>
                <span
                  title={d.status}
                  className={`px-2 py-0.5 rounded text-xs font-semibold ${
                    d.status === 'REVIEW'
                      ? 'bg-amber-100 text-amber-800'
                      : d.status === 'PROCESSED'
                      ? 'bg-green-100 text-green-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {formatEnumLabel(d.status)}
                </span>
              </div>
              {d.status_reason?.includes('INSTRUCTION_TEXT_DETECTED') && (
                <p role="alert" className="text-xs text-red-700 font-semibold bg-red-50 p-2 rounded border border-red-200">
                  ⚠ Instruction-like payment text detected. Quarantined in REVIEW.
                </p>
              )}
              <div className="pt-1">
                <button className="text-xs text-blue-600 underline font-medium hover:text-blue-800" onClick={() => koshApi.processDocument(activeSellerId!, d.id).then(refresh)}>
                  Process document
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="rounded border bg-gray-50 p-6 text-center text-sm text-gray-500">
            <p>No documents uploaded yet.</p>
            <p className="text-xs text-gray-400 mt-1">Upload sales register CSV, purchase register CSV, bank statement JSON, or invoice PDFs above.</p>
          </div>
        )}
      </div>
    </section>
  )
}
