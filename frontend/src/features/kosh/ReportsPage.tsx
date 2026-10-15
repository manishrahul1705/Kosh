import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  FileText,
  Download,
  Share2,
  Shield,
  KeyRound,
  Trash2,
  ExternalLink,
  Sparkles,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { SandboxBanner } from '@/components/ui/SandboxBanner'

export const ReportsPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [recipient, setRecipient] = useState('')
  const [expiry, setExpiry] = useState('')
  const [message, setMessage] = useState('')

  const query = useQuery({
    queryKey: ['kosh', 'reports', activeSellerId],
    queryFn: () => koshApi.reports(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const consents = useQuery({
    queryKey: ['kosh', 'sharing-consents', activeSellerId],
    queryFn: () => koshApi.sharingConsents(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const run = async (task: () => Promise<unknown>) => {
    try {
      const result = await task()
      setMessage(JSON.stringify(result))
      await qc.invalidateQueries({ queryKey: ['kosh'] })
    } catch (error) {
      setMessage(String(error))
    }
  }

  return (
    <section aria-label="Cash reports" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <FileText size={20} className="text-blue-600" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Cash-position application pack</h2>
          </div>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            One-page computed forecast, alert, plan, options evidence and audit snapshot. Generation is T1; sharing is T3 with exact consent and OTP.
          </p>
        </div>

        {query.data?.role !== 'VIEWER' && (
          <button
            className="btn-primary self-start sm:self-auto text-xs py-2 px-4"
            onClick={() => void run(() => koshApi.generateReport(activeSellerId!))}
          >
            <Sparkles size={13} />
            Generate internal PDF
          </button>
        )}
      </div>

      {message && (
        <div role="status" className="p-3 rounded-xl bg-blue-50 border border-blue-200 text-xs font-semibold text-blue-900 overflow-x-auto font-mono">
          {message}
        </div>
      )}

      {/* Grant Scoped Sharing Consent */}
      {['OWNER', 'APPROVER'].includes(query.data?.role ?? '') && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void run(() =>
              koshApi.grantSharingConsent(activeSellerId!, {
                purpose: 'SHARE_DATA_PACK',
                recipient_id: recipient,
                fields: ['cash_report_pdf', 'forecast', 'plan', 'options', 'audit_hash'],
                expires_at: new Date(expiry).toISOString(),
              })
            )
          }}
          className="card p-5 space-y-4 border-blue-200 bg-gradient-to-r from-blue-50/50 to-indigo-50/30"
        >
          <div className="border-b border-blue-100 pb-2.5">
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-blue-700" />
              <h3 className="font-bold text-sm text-blue-950 tracking-tight">Share Application Pack</h3>
            </div>
            <p className="text-xs text-blue-800 mt-0.5">
              Consent scope: cash PDF, forecast, plan, options and audit hash for the selected recipient only.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Registered recipient</label>
              <select
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                className="select text-xs"
              >
                <option value="">Select recipient</option>
                {query.data?.recipients.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="label">Consent expiry</label>
              <input
                required
                type="datetime-local"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
                className="input text-xs"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={!recipient}
            className="btn-primary text-xs py-1.5 px-4"
          >
            <KeyRound size={13} />
            Grant scoped sharing consent
          </button>
        </form>
      )}

      {/* Reports List */}
      <div className="space-y-4">
        <h3 className="font-bold text-sm text-slate-900 tracking-tight">Generated Reports</h3>
        {!query.data?.items.length && (
          <div className="card p-8 text-center text-xs text-slate-400">
            No application pack reports generated yet.
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {query.data?.items.map((r) => (
            <article key={r.id} className="card p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
                <h4 className="font-bold text-sm text-slate-900">
                  Report #{r.id} · <span className="font-semibold text-emerald-700">{r.status}</span>
                </h4>
                <span className="text-[10px] font-mono text-slate-400">{r.evidence_ref}</span>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase text-slate-400">SHA-256 Digest</span>
                <code className="block p-2 rounded-lg bg-slate-50 border border-slate-200 text-[10px] font-mono text-slate-600 truncate">
                  {r.pdf_sha256}
                </code>
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-100">
                <button
                  className="btn-secondary text-xs py-1.5 px-3"
                  onClick={() =>
                    void run(async () => {
                      const blob = await koshApi.downloadReport(activeSellerId!, r.id)
                      const url = URL.createObjectURL(blob)
                      const link = document.createElement('a')
                      link.href = url
                      link.download = `kosh-cash-${r.id}.pdf`
                      link.click()
                      URL.revokeObjectURL(url)
                      return 'Downloaded'
                    })
                  }
                >
                  <Download size={13} />
                  Download PDF {r.id}
                </button>

                {query.data?.role !== 'VIEWER' && (
                  <button
                    disabled={!recipient}
                    className="btn-primary text-xs py-1.5 px-3"
                    onClick={() => void run(() => koshApi.shareReport(activeSellerId!, r.id, recipient))}
                  >
                    <Share2 size={13} />
                    Propose T3 sharing {r.id}
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>

      {/* Sharing Consents */}
      <div className="card p-5 space-y-3">
        <h3 className="font-bold text-sm text-slate-900 tracking-tight">Sharing consent scope and revocation</h3>
        <div className="space-y-2">
          {consents.data?.items.map((c) => (
            <div
              key={c.id}
              className="p-3 rounded-lg bg-slate-50 border border-slate-200 flex flex-wrap items-center justify-between text-xs gap-2"
            >
              <div>
                <strong>{c.recipient_id}</strong> · {c.purpose} ·{' '}
                <span className="text-slate-500">{c.fields.join(', ')}</span> ·{' '}
                <span className="font-bold text-emerald-700">{c.status}</span> until {c.expires_at}
              </div>
              {['OWNER', 'APPROVER'].includes(query.data?.role ?? '') && c.status === 'ACTIVE' && (
                <button
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-600 hover:text-rose-800"
                  onClick={() => void run(() => koshApi.revokeSharingConsent(activeSellerId!, c.id))}
                >
                  <Trash2 size={11} />
                  Revoke sharing consent {c.id}
                </button>
              )}
            </div>
          ))}
          {!consents.data?.items.length && (
            <p className="text-xs text-slate-400">No active sharing consents.</p>
          )}
        </div>

        <div className="pt-2">
          <Link
            to="/approvals"
            className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline"
          >
            Review sharing intents in Approvals
            <ExternalLink size={11} />
          </Link>
        </div>
      </div>
    </section>
  )
}

