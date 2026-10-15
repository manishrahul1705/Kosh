import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  History,
  Download,
  ShieldCheck,
  ShieldAlert,
  Hash,
  CheckCircle2,
  AlertTriangle,
  Lock,
} from 'lucide-react'
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
        <h2 className="text-xl font-bold text-slate-900 tracking-tight">Audit</h2>
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-semibold text-rose-700">
          Failed to load audit records. Please ensure the backend is running.
        </div>
      </section>
    )
  }

  return (
    <section aria-label="Audit" className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <History size={20} className="text-blue-600" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Audit</h2>
          </div>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Cryptographically sealed, hash-chained audit log of all system decisions, policy checks, and owner interventions.
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          <button
            className="btn-secondary text-xs py-1.5 px-3"
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
            <Download size={13} />
            Export JSONL
          </button>
          <button
            className="btn-primary text-xs py-1.5 px-3.5"
            onClick={() =>
              koshApi.verifyAudit(activeSellerId!).then((r) =>
                setVerification(r.valid ? `VALID, ${r.entries} entries` : `BROKEN: ${r.reason}`)
              )
            }
          >
            <ShieldCheck size={13} />
            Verify chain
          </button>
        </div>
      </div>

      {/* Security Events Overview */}
      <div className="card p-5 space-y-3">
        <div className="flex items-center gap-2 border-b border-slate-100 pb-2.5">
          <Lock size={15} className="text-blue-600" />
          <h3 className="font-bold text-xs uppercase tracking-wider text-slate-700">Security events</h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
          {Object.entries(counters.data?.counts ?? {}).map(([key, value]) => (
            <div
              key={key}
              className={`p-3 rounded-xl border ${
                value > 0 && key.includes('injection')
                  ? 'bg-amber-50/80 border-amber-200 text-amber-900 font-bold'
                  : value > 0 && (key.includes('blocked') || key.includes('failed'))
                  ? 'bg-rose-50/80 border-rose-200 text-rose-900 font-bold'
                  : 'bg-slate-50 border-slate-200/80 text-slate-700 font-medium'
              }`}
            >
              <span className="block text-[11px] capitalize text-slate-500 mb-0.5">
                {key.replace(/_/g, ' ')}
              </span>
              <span className="text-base font-bold">
                {key.replace(/_/g, ' ')}: {value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Verification Status Banner */}
      {verification && (
        <div
          role="status"
          className={`p-4 rounded-xl text-xs font-bold flex items-center gap-2.5 border ${
            verification.startsWith('VALID')
              ? 'bg-emerald-50 text-emerald-900 border-emerald-200'
              : 'bg-rose-50 text-rose-900 border-rose-200'
          }`}
        >
          {verification.startsWith('VALID') ? (
            <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
          ) : (
            <AlertTriangle size={16} className="text-rose-600 shrink-0" />
          )}
          <span>Chain Verification: {verification}</span>
        </div>
      )}

      {/* Cryptographic Audit Ledger */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-base text-slate-900 tracking-tight">Cryptographic Audit Ledger</h3>
          <span className="text-xs text-slate-500">{query.data?.items.length ?? 0} entries</span>
        </div>

        {query.data?.items.length ? (
          <div className="space-y-2">
            {query.data.items.map((row) => (
              <div
                key={row.sequence}
                className="card p-3.5 flex flex-wrap items-center justify-between gap-2 hover:border-slate-300 transition-colors text-xs"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-bold border border-slate-200">
                    #{row.sequence}
                  </span>
                  <span className="font-bold text-slate-900">{row.action}</span>
                </div>

                <div className="flex items-center gap-2 text-slate-500 text-[11px]">
                  <span>{row.actor_type}</span>
                  <span>·</span>
                  <span className="px-1.5 py-0.2 rounded font-bold bg-blue-100 text-blue-800 text-[10px]">
                    {row.tier}
                  </span>
                  <span>·</span>
                  <span
                    title={row.policy_decision}
                    className="font-semibold text-slate-800"
                  >
                    {formatEnumLabel(row.policy_decision)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-10 text-center text-xs text-slate-500 space-y-2 border-dashed">
            <Hash size={32} className="mx-auto text-slate-300" />
            <p className="font-semibold text-slate-700">No audit entries yet.</p>
            <p className="text-slate-400 max-w-sm mx-auto">
              Actions taken across Kosh will automatically generate cryptographic audit entries here.
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

