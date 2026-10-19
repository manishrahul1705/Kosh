import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  TrendingUp,
  Info,
  Calendar,
  Layers,
  ExternalLink,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'

export const RevenuePage = () => {
  const { activeSellerId } = useSeller()
  const query = useQuery({
    queryKey: ['kosh', 'revenue', activeSellerId],
    queryFn: () => koshApi.revenueSignal(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const weeks = query.data?.weeks ?? []
  const totalPredictedPaise = weeks.reduce((acc, w) => acc + (w.predicted_revenue_paise || 0), 0)
  const avgPredictedPaise = weeks.length > 0 ? Math.round(totalPredictedPaise / weeks.length) : 0
  const totalLevelPaise = weeks.reduce((acc, w) => acc + (w.level_contribution_paise || 0), 0)
  const totalTrendPaise = weeks.reduce((acc, w) => acc + (w.trend_contribution_paise || 0), 0)

  return (
    <section aria-label="Revenue signal" className="space-y-6">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Optional revenue signal</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Transparent level and trend decomposition from owned invoice histories.
          </p>
        </div>
      </div>

      {/* Revenue Signal Summary Metrics */}
      {query.data?.history && query.data.history.length > 0 && <Card>
        <h3 className="font-semibold text-sm mb-2">Signal history</h3>
        <div className="flex gap-6 text-xs">{query.data.history.map(point => <p key={point.as_of}>
          <span className="block">{point.as_of}</span><strong>{formatPaiseINR(point.total_paise)}</strong>
        </p>)}</div>
      </Card>}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl border border-metal-200/80 dark:border-metal-800 bg-white dark:bg-metal-900 shadow-2xs space-y-1">
          <span className="text-[11px] font-bold uppercase tracking-wider text-metal-400">
            Total 13-Week Signal
          </span>
          <p className="text-2xl font-bold font-mono text-primary-700 dark:text-primary-300">
            {formatPaiseINR(totalPredictedPaise)}
          </p>
          <span className="text-xs text-metal-500 dark:text-metal-400 block">
            Sum of weekly forecasted receipts
          </span>
        </div>

        <div className="p-4 rounded-xl border border-metal-200/80 dark:border-metal-800 bg-white dark:bg-metal-900 shadow-2xs space-y-1">
          <span className="text-[11px] font-bold uppercase tracking-wider text-metal-400">
            Weekly Average Inflow
          </span>
          <p className="text-2xl font-bold font-mono text-metal-900 dark:text-white">
            {formatPaiseINR(avgPredictedPaise)}
          </p>
          <span className="text-xs text-metal-500 dark:text-metal-400 block">
            Projected weekly run-rate
          </span>
        </div>

        <div className="p-4 rounded-xl border border-metal-200/80 dark:border-metal-800 bg-white dark:bg-metal-900 shadow-2xs space-y-1">
          <span className="text-[11px] font-bold uppercase tracking-wider text-metal-400">
            Baseline vs Trend Outlay
          </span>
          <div className="flex flex-wrap items-baseline gap-1 font-mono font-bold text-sm text-metal-800 dark:text-metal-200">
            <span>{formatPaiseINR(totalLevelPaise)}</span>
            <span className="text-metal-400 font-normal">/</span>
            <span className="text-primary-700 dark:text-primary-300">{formatPaiseINR(totalTrendPaise)}</span>
          </div>
          <span className="text-xs text-metal-500 dark:text-metal-400 block">
            Level baseline / additive trend
          </span>
        </div>
      </div>

      {/* Model Metadata Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <Card className="space-y-1">
          <span className="text-[10px] font-bold uppercase text-metal-400 tracking-wider">Model</span>
          <p className="text-xs font-bold text-metal-900 dark:text-white">{query.data?.model ?? 'Holt Linear / Fallback'}</p>
        </Card>
        <Card className="space-y-1">
          <span className="text-[10px] font-bold uppercase text-metal-400 tracking-wider">Rationale</span>
          <p className="text-xs font-semibold text-metal-800 dark:text-metal-200">{query.data?.reason ?? 'Decomposes owned historical invoices without fabricating external benchmarks'}</p>
        </Card>
        <Card className="space-y-1">
          <span className="text-[10px] font-bold uppercase text-metal-400 tracking-wider">Explainability</span>
          <p className="text-xs font-semibold text-metal-800 dark:text-metal-200">{query.data?.explainability ?? 'Level and slope parameters fitted directly on confirmed payment dates'}</p>
        </Card>
        <Card className="space-y-1">
          <span className="text-[10px] font-bold uppercase text-metal-400 tracking-wider">Cash Timing</span>
          <p className="text-xs font-semibold text-metal-800 dark:text-metal-200">{query.data?.cash_timing ?? 'Aligned to 13-week forecast horizon'}</p>
        </Card>
      </div>

      <div className="p-3.5 rounded-xl bg-primary-50/70 dark:bg-primary-950/30 border border-primary-200 dark:border-primary-800 text-xs text-primary-950 dark:text-primary-200 flex items-start gap-2.5">
        <Info size={15} className="text-primary-600 shrink-0 mt-0.5" />
        <span className="leading-relaxed">
          Source: {query.data?.source ?? 'Owned historical invoices'}. Enable or disable this separately labelled input on{' '}
          <Link to="/cash" className="font-bold underline hover:text-primary-950 dark:hover:text-white">
            Cash
          </Link>
          . Monte Carlo remains the authoritative cash forecast.
        </span>
      </div>

      {/* Breakdown Table */}
      <Card noPadding className="overflow-hidden">
        <div className="p-4 border-b border-metal-100 dark:border-metal-800 flex items-center justify-between bg-white dark:bg-metal-900">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Weekly Contribution Breakdown</h3>
          </div>
          <span className="text-xs text-metal-500 dark:text-metal-400">{query.data?.weeks.length ?? 0} weeks</span>
        </div>
        <div className="table-container border-0 shadow-none rounded-none">
          <table>
            <thead>
              <tr>
                <th>Issue week</th>
                <th>Revenue signal</th>
                <th>Level contribution</th>
                <th>Trend contribution</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-metal-100 dark:divide-metal-800">
              {query.data?.weeks?.map((w) => (
                <tr key={w.week_index} className="hover:bg-metal-50/80 dark:hover:bg-metal-800/50">
                  <td className="font-bold text-metal-900 dark:text-white">Week {w.week_index}</td>
                  <td className="font-bold text-primary-700 dark:text-primary-300">{formatPaiseINR(w.predicted_revenue_paise)}</td>
                  <td className="font-semibold text-metal-800 dark:text-metal-200">{formatPaiseINR(w.level_contribution_paise)}</td>
                  <td className="font-semibold text-metal-800 dark:text-metal-200">{formatPaiseINR(w.trend_contribution_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </section>
  )
}
