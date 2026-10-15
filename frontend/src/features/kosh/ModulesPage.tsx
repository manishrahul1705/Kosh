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
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'

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

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Kosh modules</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Every native add-on remains listed. Owner flags suppress its inputs and new actions; changing a flag refreshes the current forecast with the same seed. Revenue and extra customer-history inputs also have explicit forecast switches.
          </p>
        </div>
      </div>

      {message && (
        <div role="status" className="p-3.5 rounded-xl bg-primary-50 dark:bg-primary-950/40 border border-primary-200 dark:border-primary-800 text-xs font-semibold text-primary-800 dark:text-primary-200 flex items-center gap-2">
          <CheckCircle2 size={15} className="text-primary-600 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {/* Module Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {query.data?.items?.map((item) => (
          <article
            key={item.module}
            className={`card p-5 space-y-3.5 flex flex-col justify-between transition-all ${
              item.enabled
                ? 'border-metal-200/90 dark:border-metal-800 hover:border-primary-300 dark:hover:border-primary-700 shadow-metal hover:shadow-metal-lg'
                : 'opacity-70 border-dashed border-metal-300 dark:border-metal-700 bg-metal-50/50 dark:bg-metal-900/40'
            }`}
          >
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="p-2.5 rounded-xl bg-primary-50 dark:bg-primary-950/50 text-primary-600 dark:text-primary-400 shrink-0">
                  <Layers size={18} />
                </div>
                <label className="inline-flex items-center gap-2 cursor-pointer text-xs font-bold text-metal-700 dark:text-metal-300">
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
                    className="rounded text-primary-600 focus:ring-primary-500"
                  />
                  <span>{item.enabled ? 'ON' : 'OFF'} · remains visible</span>
                </label>
              </div>

              <div>
                <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">
                  <Link
                    to={item.href}
                    className="hover:text-primary-600 dark:hover:text-primary-400 inline-flex items-center gap-1"
                  >
                    {item.name}
                    <ExternalLink size={12} className="opacity-50" />
                  </Link>
                </h3>
                <p className="text-xs text-metal-500 mt-1">
                  Cash feed: <strong className="text-metal-700 dark:text-metal-300">{item.cash_feed}</strong>
                </p>
              </div>
            </div>

            <div className="pt-2 border-t border-metal-100 dark:border-metal-800 flex items-center justify-between text-xs">
              <span className="text-[11px] font-mono text-metal-400 capitalize">{item.module}</span>
              <Link
                to={item.href}
                className="inline-flex items-center gap-1 font-semibold text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300"
              >
                Open module
                <ArrowRight size={12} />
              </Link>
            </div>
          </article>
        ))}
      </div>

      {/* Footer Navigation Links */}
      <div className="flex items-center gap-4 pt-4 border-t border-metal-200/80 dark:border-metal-800 text-xs">
        <Link
          to="/"
          className="inline-flex items-center gap-1 font-semibold text-primary-600 dark:text-primary-400 hover:underline"
        >
          GeM tenders
          <ArrowRight size={12} />
        </Link>
        <Link
          to="/cash"
          className="inline-flex items-center gap-1 font-semibold text-primary-600 dark:text-primary-400 hover:underline"
        >
          Cash forecast
          <ArrowRight size={12} />
        </Link>
      </div>
    </section>
  )
}
