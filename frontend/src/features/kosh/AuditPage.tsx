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
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'

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
        <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Audit</h2>
        <div role="alert" className="rounded-xl border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 p-4 text-xs font-semibold text-rose-700 dark:text-rose-300">
          Failed to load audit records. Please ensure the backend is running.
        </div>
      </section>
    )
  }

  if (query.data && !Array.isArray(query.data.items)) {
    return (
      <section aria-label="Audit" className="space-y-4">
        <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Audit</h2>
        <div role="alert" className="rounded-xl border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 p-4 text-xs font-semibold text-rose-700 dark:text-rose-300">
          Received an incompatible or malformed audit response from the server.
        </div>
      </section>
    )
  }

  return (
    <section aria-label="Audit" className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Audit</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Cryptographically sealed, hash-chained audit log of all system decisions, policy checks, and owner interventions.
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          <Button
            variant="secondary"
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
          </Button>
          <Button
            variant="primary"
            onClick={() =>
              koshApi.verifyAudit(activeSellerId!).then((r) =>
                setVerification(r.valid ? `VALID, ${r.entries} entries` : `BROKEN: ${r.reason}`)
              )
            }
          >
            <ShieldCheck size={13} />
            Verify chain
          </Button>
        </div>
      </div>

      {/* Security Events Overview */}
      <Card noPadding className="p-5 space-y-3">
        <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-2.5">
          <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
          <h3 className="font-bold text-xs uppercase tracking-wider text-metal-700 dark:text-metal-300">Security events</h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
          {Object.entries(counters.data?.counts ?? {}).map(([key, value]) => (
            <div
              key={key}
              className={`p-3.5 rounded-xl border transition-all ${
                value > 0 && key.includes('injection')
                  ? 'bg-amber-50/80 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800 text-amber-900 dark:text-amber-200 font-bold'
                  : value > 0 && (key.includes('blocked') || key.includes('failed'))
                  ? 'bg-rose-50/80 dark:bg-rose-950/40 border-rose-200 dark:border-rose-800 text-rose-900 dark:text-rose-200 font-bold'
                  : 'bg-metal-50 dark:bg-metal-800/60 border-metal-200/80 dark:border-metal-700 text-metal-700 dark:text-metal-300 font-medium'
              }`}
            >
              <span className="block text-[11px] capitalize text-metal-500 mb-0.5">
                {key.replace(/_/g, ' ')}
              </span>
              <span className="text-base font-bold">
                {key.replace(/_/g, ' ')}: {value}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* Verification Status Banner */}
      {verification && (
        <div
          role="status"
          className={`p-4 rounded-2xl text-xs font-bold flex items-center gap-2.5 border shadow-xs ${
            verification.startsWith('VALID')
              ? 'bg-primary-50 dark:bg-primary-950/40 text-primary-900 dark:text-primary-200 border-primary-200 dark:border-primary-800'
              : 'bg-rose-50 dark:bg-rose-950/40 text-rose-900 dark:text-rose-200 border-rose-200 dark:border-rose-800'
          }`}
        >
          {verification.startsWith('VALID') ? (
            <CheckCircle2 size={16} className="text-primary-600 shrink-0" />
          ) : (
            <AlertTriangle size={16} className="text-rose-600 shrink-0" />
          )}
          <span>Chain Verification: {verification}</span>
        </div>
      )}

      {/* Cryptographic Audit Ledger */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-base text-metal-900 dark:text-white tracking-tight">Cryptographic Audit Ledger</h3>
          </div>
          <span className="text-xs text-metal-500 dark:text-metal-400">{query.data?.items.length ?? 0} entries</span>
        </div>

        {query.data?.items.length ? (
          <div className="space-y-2">
            {query.data?.items?.map((row) => (
              <div
                key={row.sequence}
                className="card p-4 flex flex-wrap items-center justify-between gap-2 hover:border-primary-300 dark:hover:border-primary-700 transition-colors text-xs"
              >
                <div className="flex items-center gap-2.5">
                  <span className="font-mono text-[11px] px-2.5 py-0.5 rounded-lg bg-metal-100 dark:bg-metal-800 text-metal-700 dark:text-metal-300 font-bold border border-metal-200 dark:border-metal-700">
                    #{row.sequence}
                  </span>
                  <span className="font-bold text-metal-900 dark:text-white">{row.action}</span>
                </div>

                <div className="flex items-center gap-2 text-metal-500 text-[11px]">
                  <span>{row.actor_type}</span>
                  <span>·</span>
                  <span className="px-2 py-0.5 rounded-full font-bold bg-primary-50 dark:bg-primary-950/50 text-primary-800 dark:text-primary-300 text-[10px] border border-primary-200 dark:border-primary-800">
                    {row.tier}
                  </span>
                  <span>·</span>
                  <span
                    title={row.policy_decision}
                    className="font-semibold text-metal-800 dark:text-metal-200"
                  >
                    {formatEnumLabel(row.policy_decision)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Card className="p-10 text-center text-xs text-metal-500 space-y-2 border-dashed">
            <Hash size={32} className="mx-auto text-metal-300 dark:text-metal-600 mb-1" />
            <p className="font-semibold text-metal-700 dark:text-metal-300">No audit entries yet.</p>
            <p className="text-metal-400 max-w-sm mx-auto">
              Actions taken across Kosh will automatically generate cryptographic audit entries here.
            </p>
          </Card>
        )}
      </div>
    </section>
  )
}
