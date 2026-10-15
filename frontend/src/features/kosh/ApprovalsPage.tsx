import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  ShieldCheck,
  ShieldAlert,
  KeyRound,
  CheckCircle2,
  XCircle,
  Play,
  RotateCcw,
  Clock,
  Terminal,
  ExternalLink,
  Lock,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
import { formatEnumLabel } from '@/lib/koshLabels'

export const ApprovalsPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [now, setNow] = useState(Date.now())
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [codes, setCodes] = useState<Record<string, string>>({})
  const [tokens, setTokens] = useState<Record<string, { approval_token: string; expires_at: string }>>({})

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setTokens({})
    setCodes({})
    setMessage('')
  }, [activeSellerId])

  const enabled = activeSellerId !== null
  const intents = useQuery({
    queryKey: ['kosh', 'intents', activeSellerId],
    queryFn: () => koshApi.actionInbox(activeSellerId!),
    enabled,
  })

  const plan = useQuery({
    queryKey: ['kosh', 'plan', activeSellerId],
    queryFn: () => koshApi.latestPlan(activeSellerId!),
    enabled,
    retry: false,
  })

  const policy = useQuery({
    queryKey: ['kosh', 'policy', activeSellerId],
    queryFn: () => koshApi.policy(activeSellerId!),
    enabled,
  })

  const canApprove = ['OWNER', 'APPROVER'].includes(intents.data?.role ?? '')

  const inbox = useQuery({
    queryKey: ['kosh', 'sandbox-inbox', activeSellerId],
    queryFn: () => koshApi.sandboxInbox(activeSellerId!),
    enabled: enabled && canApprove,
    retry: false,
  })

  const outbox = useQuery({
    queryKey: ['kosh', 'sandbox-outbox', activeSellerId],
    queryFn: () => koshApi.sandboxOutbox(activeSellerId!),
    enabled,
  })

  const timeline = useQuery({
    queryKey: ['kosh', 'executions', activeSellerId],
    queryFn: () => koshApi.executions(activeSellerId!),
    enabled,
  })

  const run = async (task: () => Promise<unknown>) => {
    setBusy(true)
    setMessage('')
    try {
      await task()
      setMessage('Saved.')
      await qc.invalidateQueries({ queryKey: ['kosh'] })
    } catch (error) {
      const e = error as { response?: { data?: { detail?: unknown } }; message?: string }
      setMessage(JSON.stringify(e.response?.data?.detail ?? e.message ?? 'Request failed'))
    } finally {
      setBusy(false)
    }
  }

  const countdown = (expiry: string | null | undefined) =>
    expiry
      ? `${Math.max(0, Math.ceil((Date.parse(expiry) - now) / 1000))} seconds remaining`
      : 'No approval token issued'

  return (
    <section aria-label="Approvals" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck size={20} className="text-blue-600" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Approvals</h2>
          </div>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Review exact server-derived parameters. Execution uses the local sandbox only.
          </p>
        </div>

        {policy.data?.role === 'OWNER' && (
          <button
            className={`btn self-start sm:self-auto text-xs py-1.5 px-3.5 ${
              policy.data.seller_kill
                ? 'bg-rose-100 text-rose-800 border border-rose-300 hover:bg-rose-200 font-bold'
                : 'btn-secondary font-semibold'
            }`}
            disabled={busy}
            onClick={() => {
              const on = !policy.data?.seller_kill
              if (
                window.confirm(
                  `${on ? 'Enable' : 'Disable'} the seller kill switch? This changes whether actions can be approved and executed.`
                )
              )
                void run(() => koshApi.killSwitch(activeSellerId!, on))
            }}
          >
            <Lock size={13} />
            {policy.data.seller_kill ? 'Disable' : 'Enable'} seller kill switch
          </button>
        )}
      </div>

      {message && (
        <div role="status" className="p-3 rounded-xl bg-blue-50 border border-blue-200 text-xs font-semibold text-blue-800">
          {message}
        </div>
      )}

      {(intents.isError || policy.isError) && (
        <div role="alert" className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs font-semibold text-rose-700">
          Unable to load approvals or policy.
        </div>
      )}

      {policy.data?.global_kill && (
        <div role="alert" className="p-3 rounded-xl bg-rose-100 border border-rose-300 text-xs font-bold text-rose-900 flex items-center gap-2">
          <ShieldAlert size={16} className="text-rose-600 shrink-0" />
          <span>Global kill switch is enabled.</span>
        </div>
      )}

      {/* Valid Plan Quick-Propose Bar */}
      {canApprove && plan.data?.status === 'VALID' && (
        <div className="card p-4 space-y-3 bg-gradient-to-r from-blue-50/70 to-indigo-50/40 border-blue-200">
          <h3 className="font-bold text-sm text-blue-950 tracking-tight">
            Create an intent from the current valid plan
          </h3>
          <div className="flex flex-wrap gap-2">
            {plan.data.lines.map((line) => (
              <button
                className="btn-secondary text-xs py-1.5 px-3 bg-white hover:bg-blue-50 hover:text-blue-700"
                key={line.id}
                disabled={busy}
                onClick={() => void run(() => koshApi.proposeIntent(activeSellerId!, line.id))}
              >
                Propose {line.product_id} (Line {line.id})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Intent Inbox */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-base text-slate-900 tracking-tight">Intent inbox</h3>
          <span className="text-xs text-slate-500">{intents.data?.items.length ?? 0} intents</span>
        </div>

        {!intents.data?.items.length && (
          <div className="card p-10 text-center text-xs text-slate-500 space-y-2 border-dashed">
            <ShieldCheck size={32} className="mx-auto text-slate-300" />
            <p className="font-semibold text-slate-700">No action intents.</p>
            <p className="text-slate-400 max-w-sm mx-auto">
              Generate a plan on the Plan page to propose financing or reminder actions.
            </p>
          </div>
        )}

        <div className="space-y-4">
          {intents.data?.items.map((intent) => {
            const token = tokens[intent.id]
            return (
              <article
                key={intent.id}
                className="card p-5 space-y-4 hover:border-slate-300 transition-colors"
              >
                {/* Header Row */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2.5">
                    <h4 className="font-bold text-sm text-slate-900">{intent.action_type}</h4>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        intent.tier === 'T3'
                          ? 'bg-purple-100 text-purple-800 border border-purple-200'
                          : intent.tier === 'T2'
                          ? 'bg-blue-100 text-blue-800 border border-blue-200'
                          : 'bg-slate-100 text-slate-800 border border-slate-200'
                      }`}
                    >
                      {intent.tier}
                    </span>
                    <span
                      className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-800 border border-slate-200"
                      title={intent.status}
                    >
                      {formatEnumLabel(intent.status)}
                    </span>
                  </div>

                  <div className="text-xs">
                    {intent.plan_line_id ? (
                      <Link
                        to={`/plan#plan-line-${intent.plan_line_id}`}
                        className="inline-flex items-center gap-1 text-blue-600 font-semibold underline hover:text-blue-800"
                      >
                        Plan line {intent.plan_line_id}
                        <ExternalLink size={11} />
                      </Link>
                    ) : (
                      <Link
                        to="/operations/collections"
                        className="inline-flex items-center gap-1 text-blue-600 font-semibold underline hover:text-blue-800"
                      >
                        Native module evidence
                        <ExternalLink size={11} />
                      </Link>
                    )}
                  </div>
                </div>

                {/* Parameters & Decisions Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="space-y-1.5">
                    <h5 className="font-bold text-slate-700 text-[11px] uppercase tracking-wider">Exact parameters</h5>
                    <pre className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-[11px] font-mono whitespace-pre-wrap text-slate-800 overflow-x-auto max-h-48">
                      {JSON.stringify(intent.params, null, 2)}
                    </pre>
                  </div>

                  <div className="space-y-1.5">
                    <h5 className="font-bold text-slate-700 text-[11px] uppercase tracking-wider">Policy reasons</h5>
                    <pre className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-[11px] font-mono whitespace-pre-wrap text-slate-800 overflow-x-auto max-h-48">
                      {JSON.stringify(intent.policy_decision, null, 2)}
                    </pre>
                  </div>
                </div>

                {/* Expiry Countdown */}
                <div className="flex items-center gap-1.5 text-xs text-slate-500 pt-1">
                  <Clock size={12} className="text-slate-400" />
                  <p>{countdown(token?.expires_at ?? intent.expires_at)}</p>
                </div>

                {/* Actions Bar */}
                <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-slate-100">
                  {canApprove && ['BLOCKED', 'EXPIRED', 'FAILED'].includes(intent.status) && (
                    <button
                      className="btn-secondary text-xs py-1.5 px-3"
                      disabled={busy}
                      onClick={() => void run(() => koshApi.recheckIntent(activeSellerId!, intent.id))}
                    >
                      <RotateCcw size={12} />
                      Recheck current policy {intent.id}
                    </button>
                  )}

                  {canApprove && ['PROPOSED', 'PENDING_APPROVAL'].includes(intent.status) && (
                    <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                      {intent.tier === 'T3' && (
                        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                          <button
                            className="btn-secondary text-xs py-1.5 px-3"
                            disabled={busy}
                            onClick={() => void run(() => koshApi.requestOtp(activeSellerId!, intent.id))}
                          >
                            <KeyRound size={12} />
                            Request OTP
                          </button>
                          <label className="inline-flex items-center gap-1.5 text-xs text-slate-700 font-semibold">
                            <span>OTP for {intent.id}</span>
                            <input
                              aria-label={`OTP for ${intent.id}`}
                              inputMode="numeric"
                              maxLength={6}
                              placeholder="6 digits"
                              value={codes[intent.id] ?? ''}
                              onChange={(e) => setCodes({ ...codes, [intent.id]: e.target.value })}
                              className="w-24 px-2 py-1 rounded-md border border-slate-300 text-xs text-center font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </label>
                        </div>
                      )}

                      <button
                        className="btn-primary text-xs py-1.5 px-3.5 bg-emerald-600 hover:bg-emerald-700"
                        disabled={busy || (intent.tier === 'T3' && !/^\d{6}$/.test(codes[intent.id] ?? ''))}
                        onClick={() =>
                          void run(async () => {
                            const value = await koshApi.approveIntent(activeSellerId!, intent.id, codes[intent.id])
                            setTokens({ ...tokens, [intent.id]: value })
                            setCodes({ ...codes, [intent.id]: '' })
                          })
                        }
                      >
                        <CheckCircle2 size={12} />
                        Approve {intent.id}
                      </button>

                      <button
                        className="btn-danger text-xs py-1.5 px-3"
                        disabled={busy}
                        onClick={() => void run(() => koshApi.rejectIntent(activeSellerId!, intent.id))}
                      >
                        <XCircle size={12} />
                        Reject {intent.id}
                      </button>
                    </div>
                  )}

                  {canApprove && intent.status === 'APPROVED' && (
                    <button
                      className="btn-danger text-xs py-1.5 px-3"
                      disabled={busy}
                      onClick={() => void run(() => koshApi.rejectIntent(activeSellerId!, intent.id))}
                    >
                      <XCircle size={12} />
                      Reject approved intent {intent.id}
                    </button>
                  )}

                  {canApprove && intent.status === 'APPROVED' && token && (
                    <button
                      className="btn-primary text-xs py-1.5 px-3.5 bg-blue-700 hover:bg-blue-800"
                      disabled={busy || Date.parse(token.expires_at) <= now}
                      onClick={() =>
                        void run(async () => {
                          await koshApi.executeIntent(activeSellerId!, intent.id, token.approval_token)
                          setTokens((current) => {
                            const next = { ...current }
                            delete next[intent.id]
                            return next
                          })
                        })
                      }
                    >
                      <Play size={12} />
                      Execute in sandbox {intent.id}
                    </button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      </div>

      {/* Sandbox Sub-sections */}
      <div className="space-y-4 pt-4 border-t border-slate-200/80">
        <div className="card p-5 space-y-3">
          <h3 className="font-bold text-sm text-slate-900 tracking-tight flex items-center gap-2">
            <KeyRound size={15} className="text-blue-600" />
            Sandbox inbox · private OTP deliveries
          </h3>
          {inbox.isError && (
            <p className="text-xs text-slate-400">Private OTP inbox unavailable in this environment.</p>
          )}
          {inbox.data?.items.map((item) => (
            <pre className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-[11px] font-mono whitespace-pre-wrap text-slate-700" key={item.id}>
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
          {!inbox.data?.items.length && !inbox.isError && (
            <p className="text-xs text-slate-400">No OTP deliveries in inbox.</p>
          )}
        </div>

        <div className="card p-5 space-y-3">
          <h3 className="font-bold text-sm text-slate-900 tracking-tight flex items-center gap-2">
            <Terminal size={15} className="text-slate-600" />
            Sandbox messages · no external delivery
          </h3>
          {outbox.data?.items.map((item) => (
            <pre className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-[11px] font-mono whitespace-pre-wrap text-slate-700" key={item.id}>
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
          {!outbox.data?.items.length && (
            <p className="text-xs text-slate-400">No sandbox outbox messages.</p>
          )}
        </div>

        <div className="card p-5 space-y-3">
          <h3 className="font-bold text-sm text-slate-900 tracking-tight flex items-center gap-2">
            <Clock size={15} className="text-slate-600" />
            Executions timeline · before and after forecast
          </h3>
          {timeline.data?.items.map((item) => (
            <pre className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-[11px] font-mono whitespace-pre-wrap text-slate-700" key={item.id}>
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
          {!timeline.data?.items.length && (
            <p className="text-xs text-slate-400">No executions recorded yet.</p>
          )}
        </div>

        {canApprove && (
          <div className="pt-2">
            <button
              className="btn-secondary text-xs py-2 px-4"
              disabled={busy}
              onClick={() => void run(() => koshApi.blockedDocumentPayment(activeSellerId!))}
            >
              Test blocked document payment
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

