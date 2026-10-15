import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  LayoutGrid,
  CheckCircle2,
  ExternalLink,
  Layers,
  ArrowRight,
  Sparkles,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { SandboxBanner } from '@/components/ui/SandboxBanner'

export const ModulesPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [message, setMessage] = useState('')

  const query = useQuery({
    queryKey: ['kosh', 'modules', activeSellerId],
    queryFn: () => koshApi.modules(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  return (
    <section aria-label="Kosh modules" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <LayoutGrid size={20} className="text-blue-600" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Kosh modules</h2>
          </div>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Every native add-on remains listed. Owner flags suppress its inputs and new actions; changing a flag refreshes the current forecast with the same seed. Revenue and extra customer-history inputs also have explicit forecast switches.
          </p>
        </div>
      </div>

      {message && (
        <div role="status" className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs font-semibold text-emerald-800 flex items-center gap-2">
          <CheckCircle2 size={14} className="text-emerald-600 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {/* Module Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {query.data?.items.map((item) => (
          <article
            key={item.module}
            className={`card p-5 space-y-3.5 flex flex-col justify-between transition-all ${
              item.enabled
                ? 'border-slate-200/90 hover:border-blue-300'
                : 'opacity-70 border-dashed border-slate-300 bg-slate-50/50'
            }`}
          >
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="p-2 rounded-lg bg-blue-50 text-blue-600 shrink-0">
                  <Layers size={18} />
                </div>
                <label className="inline-flex items-center gap-2 cursor-pointer text-xs font-bold text-slate-700">
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    disabled={query.data?.role !== 'OWNER'}
                    onChange={(e) =>
                      void koshApi
                        .toggleModule(activeSellerId!, item.module, e.target.checked)
                        .then(async () => {
                          setMessage('Module setting saved; forecast refreshed when a base run exists.')
                          await qc.invalidateQueries({ queryKey: ['kosh'] })
                        })
                        .catch(() => setMessage('Unable to change module setting.'))
                    }
                    className="rounded text-blue-600 focus:ring-blue-500"
                  />
                  <span>{item.enabled ? 'ON' : 'OFF'} · remains visible</span>
                </label>
              </div>

              <div>
                <h3 className="font-bold text-sm text-slate-900 tracking-tight">
                  <Link
                    to={item.href}
                    className="hover:text-blue-600 inline-flex items-center gap-1"
                  >
                    {item.name}
                    <ExternalLink size={12} className="opacity-50" />
                  </Link>
                </h3>
                <p className="text-xs text-slate-500 mt-1">
                  Cash feed: <strong>{item.cash_feed}</strong>
                </p>
              </div>
            </div>

            <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
              <span className="text-[11px] font-mono text-slate-400 capitalize">{item.module}</span>
              <Link
                to={item.href}
                className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-800"
              >
                Open module
                <ArrowRight size={12} />
              </Link>
            </div>
          </article>
        ))}
      </div>

      {/* Footer Navigation Links */}
      <div className="flex items-center gap-4 pt-4 border-t border-slate-200/80 text-xs">
        <Link
          to="/"
          className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:underline"
        >
          GeM tenders
          <ArrowRight size={12} />
        </Link>
        <Link
          to="/cash"
          className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:underline"
        >
          Cash forecast
          <ArrowRight size={12} />
        </Link>
      </div>
    </section>
  )
}

