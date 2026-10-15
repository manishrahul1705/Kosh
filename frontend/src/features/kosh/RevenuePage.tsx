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
import { SandboxBanner } from '@/components/ui/SandboxBanner'

export const RevenuePage = () => {
  const { activeSellerId } = useSeller()
  const query = useQuery({
    queryKey: ['kosh', 'revenue', activeSellerId],
    queryFn: () => koshApi.revenueSignal(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  return (
    <section aria-label="Revenue signal" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <TrendingUp size={20} className="text-blue-600" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Optional revenue signal</h2>
          </div>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Transparent level and trend decomposition from owned invoice histories.
          </p>
        </div>
      </div>

      {/* Model Metadata Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="card p-4 space-y-1">
          <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">Model</span>
          <p className="text-xs font-bold text-slate-900">{query.data?.model}</p>
        </div>
        <div className="card p-4 space-y-1">
          <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">Rationale</span>
          <p className="text-xs font-semibold text-slate-800">{query.data?.reason}</p>
        </div>
        <div className="card p-4 space-y-1">
          <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">Explainability</span>
          <p className="text-xs font-semibold text-slate-800">{query.data?.explainability}</p>
        </div>
        <div className="card p-4 space-y-1">
          <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">Cash Timing</span>
          <p className="text-xs font-semibold text-slate-800">{query.data?.cash_timing}</p>
        </div>
      </div>

      <div className="p-3.5 rounded-xl bg-blue-50 border border-blue-200 text-xs text-blue-900 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Info size={15} className="text-blue-600 shrink-0" />
          <span>
            Source: {query.data?.source}. Enable or disable this separately labelled input on{' '}
            <Link to="/cash" className="font-bold underline hover:text-blue-950">
              Cash
            </Link>
            . Monte Carlo remains the authoritative cash forecast.
          </span>
        </div>
      </div>

      {/* Breakdown Table */}
      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-bold text-sm text-slate-900 tracking-tight">Weekly Contribution Breakdown</h3>
          <span className="text-xs text-slate-500">{query.data?.weeks.length ?? 0} weeks</span>
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
            <tbody className="divide-y divide-slate-100">
              {query.data?.weeks.map((w) => (
                <tr key={w.week_index} className="hover:bg-slate-50/70">
                  <td className="font-bold text-slate-900">Week {w.week_index}</td>
                  <td className="font-bold text-blue-700">{formatPaiseINR(w.predicted_revenue_paise)}</td>
                  <td className="font-semibold text-slate-800">{formatPaiseINR(w.level_contribution_paise)}</td>
                  <td className="font-semibold text-slate-800">{formatPaiseINR(w.trend_contribution_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}

