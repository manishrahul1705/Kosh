import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDownLeft,
  ArrowUpRight,
  AlertCircle,
  Building,
  Clock,
  ExternalLink,
  CheckCircle2,
  Filter,
  Search,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { formatEnumLabel } from '@/lib/koshLabels'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { SandboxBanner } from '@/components/ui/SandboxBanner'

export const LedgerPage = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<'ALL' | 'RECEIVABLE' | 'PAYABLE' | 'REVIEW'>('ALL')
  const [search, setSearch] = useState('')

  const query = useQuery({
    queryKey: ['kosh', 'ledger', activeSellerId],
    queryFn: () => koshApi.ledger(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const obligations = useQuery({
    queryKey: ['kosh', 'obligations', activeSellerId],
    queryFn: () => koshApi.obligations(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  if (query.isLoading) return <PageLoader />
  if (query.isError) return <ErrorAlert message="Unable to load the cash ledger. Please ensure the backend is connected." />
  if (!query.data) return <p className="text-slate-500">Select a seller to view ledger.</p>

  const t = query.data.totals

  const items = query.data.items.filter((item) => {
    if (filter === 'RECEIVABLE' && item.direction !== 'RECEIVABLE') return false
    if (filter === 'PAYABLE' && item.direction !== 'PAYABLE') return false
    if (filter === 'REVIEW' && item.status !== 'REVIEW') return false
    if (search.trim()) {
      const q = search.toLowerCase()
      return item.party.toLowerCase().includes(q) || item.invoice_number.toLowerCase().includes(q)
    }
    return true
  })

  return (
    <section aria-label="Ledger" className="space-y-6">
      <SandboxBanner />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-slate-200/80 pb-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Ledger & Invoices</h2>
          <p className="text-xs sm:text-sm text-slate-600 mt-0.5">
            Real cash ledger records, open receivables and verified trade payables.
          </p>
        </div>
        {t.bank_balance_as_of && (
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-100 text-xs text-slate-600 border border-slate-200/80">
            <Clock size={12} className="text-slate-400" />
            <span>Bank balance as of: <strong>{t.bank_balance_as_of}</strong></span>
          </div>
        )}
      </div>

      {/* Metric Cards */}
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
        <div className="stat-card">
          <div className="flex items-center justify-between">
            <p className="stat-label">Open receivables</p>
            <ArrowDownLeft size={16} className="text-emerald-600" />
          </div>
          <strong className="stat-value text-emerald-600 block">{formatPaiseINR(t.open_receivables_paise)}</strong>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between">
            <p className="stat-label">Open payables (verified)</p>
            <ArrowUpRight size={16} className="text-slate-600" />
          </div>
          <strong className="stat-value text-slate-900 block">{formatPaiseINR(t.open_payables_paise)}</strong>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between">
            <p className="stat-label">Overdue</p>
            <Clock size={16} className="text-rose-600" />
          </div>
          <strong className="stat-value text-rose-600 block">{formatPaiseINR(t.overdue_receivables_paise)}</strong>
        </div>

        <div className="stat-card">
          <div className="flex items-center justify-between">
            <p className="stat-label">Bank balance</p>
            <Building size={16} className="text-blue-600" />
          </div>
          <strong className="stat-value text-blue-600 block">{formatPaiseINR(t.latest_bank_balance_paise)}</strong>
        </div>

        <div className="stat-card col-span-2 lg:col-span-1">
          <div className="flex items-center justify-between">
            <p className="stat-label">Review Required</p>
            <AlertCircle size={16} className={t.review_count > 0 ? 'text-amber-600' : 'text-slate-400'} />
          </div>
          <strong className={`stat-value block ${t.review_count > 0 ? 'text-amber-700' : 'text-slate-900'}`}>
            {t.review_count} {t.review_count === 1 ? 'invoice' : 'invoices'}
          </strong>
        </div>
      </div>

      {/* Table & Filters */}
      <div className="card overflow-hidden">
        {/* Filter Toolbar */}
        <div className="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
            <Filter size={14} className="text-slate-400 shrink-0 hidden sm:inline" />
            {(['ALL', 'RECEIVABLE', 'PAYABLE', 'REVIEW'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setFilter(mode)}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors shrink-0 ${
                  filter === mode
                    ? 'bg-blue-600 text-white shadow-2xs'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {mode === 'ALL'
                  ? 'All entries'
                  : mode === 'RECEIVABLE'
                  ? 'Receivables'
                  : mode === 'PAYABLE'
                  ? 'Payables'
                  : 'Review only'}
              </button>
            ))}
          </div>

          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by party or invoice..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 pr-3 py-1.5 rounded-lg border border-slate-300 text-xs w-full sm:w-60 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600"
            />
          </div>
        </div>

        {query.data.items.length === 0 ? (
          <div className="p-12 text-center text-xs text-slate-500 space-y-2">
            <p className="font-semibold text-slate-700">No ledger entries recorded yet.</p>
            <p className="text-slate-400 max-w-sm mx-auto">
              Connect your ERP or upload invoices on the Connect page to populate the ledger.
            </p>
          </div>
        ) : (
          <div className="table-container border-0 rounded-none shadow-none">
            <table>
              <thead>
                <tr>
                  <th>Party</th>
                  <th>Invoice</th>
                  <th>Due Date</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Evidence</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((row) => (
                  <tr
                    key={row.id}
                    className={row.status === 'REVIEW' ? 'bg-amber-50/50 hover:bg-amber-50/80' : 'hover:bg-slate-50/70'}
                  >
                    <td className="font-semibold text-slate-900">{row.party}</td>
                    <td className="font-mono text-xs text-slate-700">{row.invoice_number}</td>
                    <td className="text-slate-600 text-xs">{row.due_date}</td>
                    <td className="font-bold text-slate-900">{formatPaiseINR(row.amount_paise)}</td>
                    <td>
                      <span
                        title={row.status}
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                          row.status === 'PAID'
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                            : row.status === 'REVIEW'
                            ? 'bg-amber-100 text-amber-800 border border-amber-300 font-bold'
                            : 'bg-slate-100 text-slate-800 border border-slate-200'
                        }`}
                      >
                        {row.status === 'PAID' && <CheckCircle2 size={11} />}
                        {row.status === 'REVIEW' && <AlertCircle size={11} />}
                        {formatEnumLabel(row.status)}
                      </span>
                      {row.status === 'REVIEW' && (
                        <button
                          className="ml-2 inline-flex items-center gap-0.5 text-xs text-blue-600 font-semibold underline hover:text-blue-800"
                          onClick={() =>
                            koshApi
                              .patchInvoice(activeSellerId!, row.id, {})
                              .then(() => qc.invalidateQueries({ queryKey: ['kosh', 'ledger'] }))
                          }
                        >
                          Confirm
                        </button>
                      )}
                    </td>
                    <td>
                      <details>
                        <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700">
                          View source
                        </summary>
                        <pre className="max-w-xs whitespace-pre-wrap text-[10px] bg-slate-50 p-2 rounded-lg mt-1 border border-slate-200 font-mono text-slate-700">
                          {row.source_location || 'No source quote'}
                        </pre>
                      </details>
                    </td>
                    <td>
                      {row.direction === 'RECEIVABLE' && row.status !== 'PAID' ? (
                        <Link
                          to="/operations/collections"
                          className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 underline hover:text-blue-800"
                        >
                          Collections
                          <ExternalLink size={10} />
                        </Link>
                      ) : (
                        <span className="text-slate-300">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Obligations */}
      <div className="space-y-3">
        <h3 className="font-bold text-sm text-slate-900 tracking-tight">Obligations</h3>
        {obligations.data?.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {obligations.data.map((row, index) => (
              <div key={index} className="card p-4 space-y-1">
                <span className="text-xs font-semibold text-slate-700">{String(row.label)}</span>
                <p className="text-base font-bold text-slate-900">{formatPaiseINR(Number(row.amount_paise))}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-6 text-center text-xs text-slate-400">
            No obligations recorded.
          </div>
        )}
      </div>
    </section>
  )
}

