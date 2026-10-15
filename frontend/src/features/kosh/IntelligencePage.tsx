import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Users,
  Sliders,
  CheckCircle2,
  FileCheck2,
  Play,
  RotateCcw,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'

export const IntelligencePage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [customer, setCustomer] = useState('')
  const [po, setPo] = useState('')
  const [delay, setDelay] = useState('15')
  const [percent, setPercent] = useState('8')
  const [observations, setObservations] = useState('')
  const [date, setDate] = useState('')
  const [evidence, setEvidence] = useState('')
  const [message, setMessage] = useState('')
  const [scenario, setScenario] = useState<{
    weeks: { week_index: number; p50_closing_balance_paise: number; prob_below_buffer: number }[]
  } | null>(null)

  const query = useQuery({
    queryKey: ['kosh', 'intelligence', activeSellerId],
    queryFn: () => koshApi.intelligence(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const ops = useQuery({
    queryKey: ['kosh', 'operations', activeSellerId],
    queryFn: () => koshApi.operations(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const run = async (task: () => Promise<unknown>) => {
    try {
      await task()
      setMessage('Saved.')
      await qc.invalidateQueries({ queryKey: ['kosh'] })
    } catch (error) {
      setMessage(String(error))
    }
  }

  return (
    <section aria-label="Customer intelligence" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">
              Customer intelligence and cash what-if
            </h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Observed delays and concentration come from owned invoice evidence. Additional history is optional, labelled and owner-confirmed.
          </p>
        </div>
      </div>

      {message && (
        <div role="status" className="p-3.5 rounded-xl bg-primary-50 dark:bg-primary-950/40 border border-primary-200 dark:border-primary-800 text-xs font-semibold text-primary-800 dark:text-primary-200 flex items-center gap-2">
          <CheckCircle2 size={15} className="text-primary-600 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {/* Customers Table */}
      <Card noPadding className="overflow-hidden">
        <div className="p-4 border-b border-metal-100 dark:border-metal-800 flex items-center justify-between bg-white dark:bg-metal-900">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Observed Customer Behavior</h3>
          </div>
          <span className="text-xs text-metal-500 dark:text-metal-400">{query.data?.items.length ?? 0} counterparties</span>
        </div>
        <div className="table-container border-0 shadow-none rounded-none">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Open receivables</th>
                <th>Median delay</th>
                <th>Concentration</th>
                <th>Signal</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-metal-100 dark:divide-metal-800">
              {query.data?.items.map((item) => (
                <tr key={item.counterparty_id} className="hover:bg-metal-50/80 dark:hover:bg-metal-800/50">
                  <td className="font-bold text-metal-900 dark:text-white">{item.name}</td>
                  <td className="font-semibold text-metal-900 dark:text-white">{formatPaiseINR(item.open_receivables_paise)}</td>
                  <td className="text-metal-700 dark:text-metal-300">{item.median_delay_days ?? 'unknown'} days</td>
                  <td className="text-metal-700 dark:text-metal-300 font-medium">{item.concentration_share ?? 'unknown'}</td>
                  <td>
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-primary-50 text-primary-800 dark:bg-primary-950/50 dark:text-primary-300 border border-primary-200 dark:border-primary-800">
                      {item.credit_signal}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* What-if scenario form */}
      <Card noPadding className="p-5 space-y-4">
        <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-2.5">
          <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
          <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Scenario Simulator</h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="label">Customer</label>
            <select
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
              className="select text-xs"
            >
              <option value="">Select customer</option>
              {query.data?.items.map((i) => (
                <option key={i.counterparty_id} value={i.counterparty_id}>
                  {i.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Delay shift (days)</label>
            <input
              type="number"
              step="1"
              value={delay}
              onChange={(e) => setDelay(e.target.value)}
              className="input text-xs"
            />
          </div>

          <div>
            <label className="label">Confirmed purchase</label>
            <select
              value={po}
              onChange={(e) => setPo(e.target.value)}
              className="select text-xs"
            >
              <option value="">No material change</option>
              {ops.data?.items
                .filter((i) => i.kind === 'PO' && i.status === 'CONFIRMED')
                .map((i) => (
                  <option key={i.id} value={i.id}>
                    PO #{i.id}
                  </option>
                ))}
            </select>
          </div>

          <div>
            <label className="label">Material price change (%)</label>
            <input
              type="number"
              value={percent}
              onChange={(e) => setPercent(e.target.value)}
              className="input text-xs"
            />
          </div>
        </div>

        {query.data?.role !== 'VIEWER' && (
          <button
            className="btn-primary text-xs py-2 px-4 inline-flex items-center gap-1.5"
            onClick={() =>
              void run(async () =>
                setScenario(
                  await koshApi.intelligenceScenario(activeSellerId!, {
                    counterparty_id: customer ? Number(customer) : null,
                    delay_shift_days: customer ? Number(delay) : 0,
                    purchase_order_id: po ? Number(po) : null,
                    price_change_percent: po ? percent : '0',
                  })
                )
              )
            }
          >
            <Play size={13} />
            Run same-seed scenario
          </button>
        )}
      </Card>

      {/* Scenario Output Table */}
      {scenario && (
        <Card noPadding className="overflow-hidden border-primary-200 dark:border-primary-800">
          <div className="p-4 border-b border-primary-100 dark:border-primary-900 bg-primary-50/50 dark:bg-primary-950/30 flex items-center justify-between">
            <h3 className="font-bold text-sm text-primary-950 dark:text-primary-200 tracking-tight">Simulated Cash Path</h3>
            <button
              onClick={() => setScenario(null)}
              className="text-xs text-metal-500 hover:text-metal-800 dark:hover:text-metal-200"
            >
              Clear scenario
            </button>
          </div>
          <div className="table-container border-0 shadow-none rounded-none">
            <table>
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Scenario P50</th>
                  <th>Below buffer</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-metal-100 dark:divide-metal-800">
                {scenario.weeks.map((w) => (
                  <tr key={w.week_index} className="hover:bg-metal-50/80 dark:hover:bg-metal-800/50">
                    <td className="font-bold text-metal-900 dark:text-white">Week {w.week_index}</td>
                    <td className="font-semibold text-primary-700 dark:text-primary-300">{formatPaiseINR(w.p50_closing_balance_paise)}</td>
                    <td className="font-medium text-metal-800 dark:text-metal-200">{w.prob_below_buffer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Additional Payment Evidence Form */}
      {query.data?.role !== 'VIEWER' && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void run(() =>
              koshApi.proposeHistory(activeSellerId!, {
                counterparty_id: Number(customer),
                observed_date: date,
                delay_days: observations.split(',').map((v) => Number(v.trim())),
                evidence_ref: evidence,
              })
            )
          }}
          className="card p-5 space-y-4"
        >
          <div className="border-b border-metal-100 dark:border-metal-800 pb-2.5">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
              <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Additional payment evidence</h3>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="label">Delay observations (comma-separated whole days)</label>
              <input
                required
                placeholder="e.g. 5, 12, 18"
                value={observations}
                onChange={(e) => setObservations(e.target.value)}
                className="input text-xs"
              />
            </div>
            <div>
              <label className="label">Observed date</label>
              <input
                required
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="input text-xs"
              />
            </div>
            <div>
              <label className="label">Evidence</label>
              <input
                required
                placeholder="e.g. Bank statement ref / remittance voucher"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
                className="input text-xs"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={!customer}
            className="btn-primary text-xs py-2 px-4"
          >
            Propose history
          </button>
        </form>
      )}

      {/* Historical Evidence Records */}
      {query.data?.history && query.data.history.length > 0 && (
        <Card noPadding className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Proposed Customer Payment Evidence</h3>
          </div>
          <div className="space-y-2">
            {query.data.history.map((row) => (
              <div
                key={row.id}
                className="p-3.5 rounded-xl bg-metal-50 dark:bg-metal-800/60 border border-metal-200 dark:border-metal-700 flex flex-wrap items-center justify-between text-xs gap-2"
              >
                <div>
                  <strong className="text-metal-900 dark:text-white">{row.evidence_ref}:</strong>{' '}
                  <span className="font-semibold text-primary-700 dark:text-primary-300">{row.status}</span>
                </div>
                {query.data?.role === 'OWNER' && row.status === 'PROPOSED' && (
                  <button
                    className="btn-secondary text-[11px] py-1 px-3"
                    onClick={() => void run(() => koshApi.confirmHistory(activeSellerId!, row.id))}
                  >
                    Owner confirm history {row.id}
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </section>
  )
}
