import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { formatEnumLabel } from '@/lib/koshLabels'

export const AuditPage = () => {
  const { activeSellerId } = useSeller()
  const [verification, setVerification] = useState('')
  const counters = useQuery({
    queryKey: ['kosh', 'security-events', activeSellerId],
    queryFn: () => koshApi.securityEvents(activeSellerId!),
    enabled: activeSellerId !== null,
    retry: false,
  })
  const query = useQuery({
    queryKey: ['kosh', 'audit', activeSellerId],
    queryFn: () => koshApi.audit(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  if (query.isLoading) return <PageLoader />
  if (query.isError) {
    return (
      <section aria-label="Audit" className="space-y-4">
        <h2 className="text-xl font-semibold">Audit</h2>
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load audit records. Please ensure the backend is running.
        </div>
      </section>
    )
  }

  return (
    <section aria-label="Audit" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Audit</h2>
        <div className="flex items-center gap-2">
          <button
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
            onClick={() =>
              koshApi.exportAudit(activeSellerId!).then((text) => {
                const url = URL.createObjectURL(new Blob([text], { type: 'application/x-ndjson' }))
                const link = document.createElement('a')
                link.href = url
                link.download = `kosh-audit-${activeSellerId}.jsonl`
                link.click()
                URL.revokeObjectURL(url)
              })
            }
          >
            Export JSONL
          </button>
          <button
            className="rounded bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800"
            onClick={() =>
              koshApi.verifyAudit(activeSellerId!).then((r) =>
                setVerification(r.valid ? `VALID, ${r.entries} entries` : `BROKEN: ${r.reason}`)
              )
            }
          >
            Verify chain
          </button>
        </div>
      </div>

      <div className="rounded border bg-white p-4">
        <h3 className="font-semibold text-sm text-gray-700 mb-2">Security events</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm">
          {Object.entries(counters.data?.counts ?? {}).map(([key, value]) => (
            <p key={key} className="rounded border bg-gray-50 p-2">
              {key.replace(/_/g, ' ')}: {value}
            </p>
          ))}
        </div>
      </div>

      {verification && (
        <div
          role="status"
          className={`rounded p-3 text-sm font-semibold ${
            verification.startsWith('VALID')
              ? 'bg-green-50 text-green-800 border border-green-200'
              : 'bg-red-50 text-red-800 border border-red-200'
          }`}
        >
          Chain Verification: {verification}
        </div>
      )}

      <div className="space-y-2">
        <h3 className="font-semibold text-sm text-gray-700">Cryptographic Audit Ledger</h3>
        {query.data?.items.length ? (
          query.data.items.map((row) => (
            <div className="rounded border bg-white p-3 flex flex-wrap items-center justify-between text-sm" key={row.sequence}>
              <span className="font-medium">
                #{row.sequence} {row.action}
              </span>
              <span className="text-gray-500 text-xs">
                {row.actor_type} · <span className="font-semibold text-gray-700">{row.tier}</span> ·{' '}
                <span title={row.policy_decision} className="font-medium text-gray-800">
                  {formatEnumLabel(row.policy_decision)}
                </span>
              </span>
            </div>
          ))
        ) : (
          <div className="rounded border bg-gray-50 p-6 text-center text-sm text-gray-500">
            <p>No audit entries yet.</p>
            <p className="text-xs text-gray-400 mt-1">Actions taken across Kosh will automatically generate cryptographic audit entries here.</p>
          </div>
        )}
      </div>
    </section>
  )
}
