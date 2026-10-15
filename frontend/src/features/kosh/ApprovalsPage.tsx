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
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { formatEnumLabel } from '@/lib/koshLabels'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'

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

  if (intents.data && !Array.isArray(intents.data.items)) {
    return (
      <section aria-label="Approvals" className="space-y-6">
        <SandboxBanner />
        <ErrorAlert message="Received an incompatible or malformed action intents response from the server." />
      </section>
    )
  }

  return (
    <section aria-label="Approvals" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Approvals</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Review exact server-derived parameters. Execution uses the local sandbox only.
          </p>
        </div>

        {policy.data?.role === 'OWNER' && (
          <button
            className={`btn self-start sm:self-auto text-xs py-1.5 px-3.5 transition-all ${
              policy.data.seller_kill
                ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300 border border-rose-300 dark:border-rose-800 hover:bg-rose-200 font-bold'
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
        <div role="status" className="p-3.5 rounded-xl bg-primary-50 dark:bg-primary-950/40 border border-primary-200 dark:border-primary-800 text-xs font-semibold text-primary-800 dark:text-primary-200 flex items-center gap-2">
          <CheckCircle2 size={15} className="text-primary-600 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {(intents.isError || policy.isError) && (
        <div role="alert" className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs font-semibold text-rose-700 dark:text-rose-300">
          Unable to load approvals or policy.
        </div>
      )}

      {policy.data?.global_kill && (
        <div role="alert" className="p-3.5 rounded-xl bg-rose-100 dark:bg-rose-950/60 border border-rose-300 dark:border-rose-800 text-xs font-bold text-rose-900 dark:text-rose-200 flex items-center gap-2">
          <ShieldAlert size={16} className="text-rose-600 shrink-0" />
          <span>Global kill switch is enabled.</span>
        </div>
      )}

      {/* Valid Plan Quick-Propose Bar */}
      {canApprove && plan.data?.status === 'VALID' && (
        <div className="card p-4 space-y-3 bg-gradient-to-r from-primary-50/70 to-metal-50/40 dark:from-primary-950/30 dark:to-metal-900/40 border-primary-200 dark:border-primary-800">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-primary-950 dark:text-primary-200 tracking-tight">
              Create an intent from the current valid plan
            </h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {plan.data?.lines?.map((line) => (
              <button
                className="btn-secondary text-xs py-1.5 px-3 bg-white dark:bg-metal-800 hover:bg-primary-50 dark:hover:bg-metal-700 hover:text-primary-700"
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
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-base text-metal-900 dark:text-white tracking-tight">Intent inbox</h3>
          </div>
          <span className="text-xs text-metal-500 dark:text-metal-400">{intents.data?.items.length ?? 0} intents</span>
        </div>

        {!intents.data?.items.length && (
          <Card className="p-10 text-center text-xs text-metal-500 space-y-2 border-dashed">
            <ShieldCheck size={32} className="mx-auto text-metal-300 dark:text-metal-600 mb-1" />
            <p className="font-semibold text-metal-700 dark:text-metal-300">No action intents.</p>
            <p className="text-metal-400 max-w-sm mx-auto">
              Generate a plan on the Plan page to propose financing or reminder actions.
            </p>
          </Card>
        )}

        <div className="space-y-4">
          {intents.data?.items?.map((intent) => {
            const token = tokens[intent.id]
            return (
              <article
                key={intent.id}
                className="card p-5 space-y-4 hover:border-primary-300 dark:hover:border-primary-700 transition-colors"
              >
                {/* Header Row */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-metal-100 dark:border-metal-800 pb-3">
                  <div className="flex items-center gap-2.5">
                    <h4 className="font-bold text-sm text-metal-900 dark:text-white">{intent.action_type}</h4>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        intent.tier === 'T3'
                          ? 'bg-purple-50 text-purple-800 dark:bg-purple-950/50 dark:text-purple-300 border border-purple-200'
                          : intent.tier === 'T2'
                          ? 'bg-primary-50 text-primary-800 dark:bg-primary-950/50 dark:text-primary-300 border border-primary-200'
                          : 'bg-metal-100 text-metal-800 dark:bg-metal-800 dark:text-metal-200 border border-metal-200'
                      }`}
                    >
                      {intent.tier}
                    </span>
                    <span
                      className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-metal-100 text-metal-800 dark:bg-metal-800 dark:text-metal-200 border border-metal-200 dark:border-metal-700"
                      title={intent.status}
                    >
                      {formatEnumLabel(intent.status)}
                    </span>
                  </div>

                  <div className="text-xs">
                    {intent.plan_line_id ? (
                      <Link
                        to={`/plan#plan-line-${intent.plan_line_id}`}
                        className="inline-flex items-center gap-1 text-primary-600 dark:text-primary-400 font-semibold underline hover:text-primary-800 dark:hover:text-primary-300"
                      >
                        Plan line {intent.plan_line_id}
                        <ExternalLink size={11} />
                      </Link>
                    ) : (
                      <Link
                        to="/operations/collections"
                        className="inline-flex items-center gap-1 text-primary-600 dark:text-primary-400 font-semibold underline hover:text-primary-800 dark:hover:text-primary-300"
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
                    <h5 className="font-bold text-metal-700 dark:text-metal-300 text-[11px] uppercase tracking-wider">Exact parameters</h5>
                    <pre className="p-3 rounded-xl bg-metal-50 dark:bg-metal-800/80 border border-metal-200 dark:border-metal-700 text-[11px] font-mono whitespace-pre-wrap text-metal-800 dark:text-metal-200 overflow-x-auto max-h-48">
                      {JSON.stringify(intent.params, null, 2)}
                    </pre>
                  </div>

                  <div className="space-y-1.5">
                    <h5 className="font-bold text-metal-700 dark:text-metal-300 text-[11px] uppercase tracking-wider">Policy reasons</h5>
                    <pre className="p-3 rounded-xl bg-metal-50 dark:bg-metal-800/80 border border-metal-200 dark:border-metal-700 text-[11px] font-mono whitespace-pre-wrap text-metal-800 dark:text-metal-200 overflow-x-auto max-h-48">
                      {JSON.stringify(intent.policy_decision, null, 2)}
                    </pre>
                  </div>
                </div>

                {/* Expiry Countdown */}
                <div className="flex items-center gap-1.5 text-xs text-metal-500 dark:text-metal-400 pt-1">
                  <Clock size={12} className="text-metal-400" />
                  <p>{countdown(token?.expires_at ?? intent.expires_at)}</p>
                </div>

                {/* Actions Bar */}
                <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-metal-100 dark:border-metal-800">
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
                          <label className="inline-flex items-center gap-1.5 text-xs text-metal-700 dark:text-metal-300 font-semibold">
                            <span>OTP for {intent.id}</span>
                            <input
                              aria-label={`OTP for ${intent.id}`}
                              inputMode="numeric"
                              maxLength={6}
                              placeholder="6 digits"
                              value={codes[intent.id] ?? ''}
                              onChange={(e) => setCodes({ ...codes, [intent.id]: e.target.value })}
                              className="w-24 px-2 py-1 rounded-xl border border-metal-300 dark:border-metal-600 bg-white dark:bg-metal-900 text-xs text-center font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                          </label>
                        </div>
                      )}

                      <button
                        className="btn-primary text-xs py-1.5 px-3.5"
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
                      className="btn-primary text-xs py-1.5 px-3.5"
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
      <div className="space-y-4 pt-4 border-t border-metal-200/80 dark:border-metal-800">
        <Card noPadding className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight flex items-center gap-2">
              <KeyRound size={15} className="text-primary-600" />
              Sandbox inbox · private OTP deliveries
            </h3>
          </div>
          {inbox.isError && (
            <p className="text-xs text-metal-400">Private OTP inbox unavailable in this environment.</p>
          )}
          {inbox.data?.items?.map((item) => (
            <pre className="p-3 rounded-xl bg-metal-50 dark:bg-metal-800/80 border border-metal-200 dark:border-metal-700 text-[11px] font-mono whitespace-pre-wrap text-metal-700 dark:text-metal-300" key={item.id}>
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
          {!inbox.data?.items?.length && !inbox.isError && (
            <p className="text-xs text-metal-400">No OTP deliveries in inbox.</p>
          )}
        </Card>

        <Card noPadding className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight flex items-center gap-2">
              <Terminal size={15} className="text-metal-500" />
              Sandbox messages · no external delivery
            </h3>
          </div>
          {outbox.data?.items?.map((item) => (
            <pre className="p-3 rounded-xl bg-metal-50 dark:bg-metal-800/80 border border-metal-200 dark:border-metal-700 text-[11px] font-mono whitespace-pre-wrap text-metal-700 dark:text-metal-300" key={item.id}>
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
          {!outbox.data?.items?.length && (
            <p className="text-xs text-metal-400">No sandbox outbox messages.</p>
          )}
        </Card>

        <Card noPadding className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight flex items-center gap-2">
              <Clock size={15} className="text-metal-500" />
              Executions timeline · before and after forecast
            </h3>
          </div>
          {timeline.data?.items?.map((item) => (
            <pre className="p-3 rounded-xl bg-metal-50 dark:bg-metal-800/80 border border-metal-200 dark:border-metal-700 text-[11px] font-mono whitespace-pre-wrap text-metal-700 dark:text-metal-300" key={item.id}>
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
          {!timeline.data?.items.length && (
            <p className="text-xs text-metal-400">No executions recorded yet.</p>
          )}
        </Card>

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
