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
  FileSpreadsheet,
  FileText,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'
import { formatEnumLabel } from '@/lib/koshLabels'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'

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
  if (!query.data) return <p className="text-metal-500">Select a seller to view ledger.</p>

  if ('status' in query.data && (query.data as { status?: string }).status === 'NOT_IMPLEMENTED') {
    return (
      <section aria-label="Ledger" className="space-y-6">
        <div className="flex items-center gap-2 border-b border-metal-200/80 dark:border-metal-800 pb-4">
          <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
          <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Ledger & Invoices</h2>
        </div>
        <Card className="p-8 text-center space-y-3 max-w-xl mx-auto my-8">
          <FileText size={36} className="mx-auto text-metal-400" />
          <h3 className="text-base font-bold text-metal-900 dark:text-white">No ledger records available</h3>
          <p className="text-xs text-metal-600 dark:text-metal-400 max-w-md mx-auto">
            Connect accounting software or ingest sales invoices and purchase bills to populate the ledger.
          </p>
        </Card>
      </section>
    )
  }

  if (!query.data.totals || !Array.isArray(query.data.items)) {
    return (
      <section aria-label="Ledger" className="space-y-6">
        <div className="flex items-center gap-2 border-b border-metal-200/80 dark:border-metal-800 pb-4">
          <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
          <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Ledger & Invoices</h2>
        </div>
        <ErrorAlert message="Received an incompatible or malformed ledger response from the server." />
      </section>
    )
  }

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
      {/* Header with MetalliSense emerald styling */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">Ledger & Invoices</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Real cash ledger records, open receivables and verified trade payables.
          </p>
        </div>
        {t.bank_balance_as_of && (
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white dark:bg-metal-900 text-xs text-metal-600 dark:text-metal-300 border border-metal-200/80 dark:border-metal-800 shadow-xs">
            <Clock size={13} className="text-primary-500" />
            <span>Bank balance as of: <strong className="text-metal-900 dark:text-white">{t.bank_balance_as_of}</strong></span>
          </div>
        )}
      </div>

      {/* Metric Cards - MetalliSense KPI card treatment */}
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6 min-w-0">
        <div className="stat-card min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="stat-label truncate">Open receivables</p>
            <div className="w-7 h-7 rounded-lg bg-primary-50 dark:bg-primary-950/50 flex items-center justify-center shrink-0">
              <ArrowDownLeft size={15} className="text-primary-600 dark:text-primary-400" />
            </div>
          </div>
          <strong className="stat-value text-primary-600 dark:text-primary-400 block mt-1 truncate" title={formatPaiseINR(t.open_receivables_paise)}>
            {formatPaiseINR(t.open_receivables_paise)}
          </strong>
        </div>

        <div className="stat-card min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="stat-label truncate" title="Open payables (verified)">Open payables (verified)</p>
            <div className="w-7 h-7 rounded-lg bg-metal-100 dark:bg-metal-800 flex items-center justify-center shrink-0">
              <ArrowUpRight size={15} className="text-metal-600 dark:text-metal-400" />
            </div>
          </div>
          <strong className="stat-value text-metal-900 dark:text-white block mt-1 truncate" title={formatPaiseINR(t.open_payables_paise)}>
            {formatPaiseINR(t.open_payables_paise)}
          </strong>
        </div>

        <div className="stat-card min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="stat-label truncate" title="Held-for-review payables">Held-for-review payables</p>
            <div className="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-950/50 flex items-center justify-center shrink-0">
              <AlertCircle size={15} className="text-amber-600 dark:text-amber-400" />
            </div>
          </div>
          <strong
            className="stat-value text-amber-700 dark:text-amber-400 block mt-1 truncate"
            title={formatPaiseINR(
              t.held_for_review_payables_paise ??
                query.data.items
                  .filter((i) => i.direction === 'PAYABLE' && i.status === 'REVIEW')
                  .reduce((acc, i) => acc + i.amount_paise, 0)
            )}
          >
            {formatPaiseINR(
              t.held_for_review_payables_paise ??
                query.data.items
                  .filter((i) => i.direction === 'PAYABLE' && i.status === 'REVIEW')
                  .reduce((acc, i) => acc + i.amount_paise, 0)
            )}
          </strong>
        </div>

        <div className="stat-card min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="stat-label truncate">Overdue</p>
            <div className="w-7 h-7 rounded-lg bg-rose-50 dark:bg-rose-950/50 flex items-center justify-center shrink-0">
              <Clock size={15} className="text-rose-600 dark:text-rose-400" />
            </div>
          </div>
          <strong className="stat-value text-rose-600 dark:text-rose-400 block mt-1 truncate" title={formatPaiseINR(t.overdue_receivables_paise)}>
            {formatPaiseINR(t.overdue_receivables_paise)}
          </strong>
        </div>

        <div className="stat-card min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="stat-label truncate">Bank balance</p>
            <div className="w-7 h-7 rounded-lg bg-primary-50 dark:bg-primary-950/50 flex items-center justify-center shrink-0">
              <Building size={15} className="text-primary-600 dark:text-primary-400" />
            </div>
          </div>
          <strong className="stat-value text-primary-700 dark:text-primary-300 block mt-1 truncate" title={formatPaiseINR(t.latest_bank_balance_paise)}>
            {formatPaiseINR(t.latest_bank_balance_paise)}
          </strong>
        </div>

        <div className="stat-card min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="stat-label truncate">Review Required</p>
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${t.review_count > 0 ? 'bg-amber-50 dark:bg-amber-950/50' : 'bg-metal-100 dark:bg-metal-800'}`}>
              <AlertCircle size={15} className={t.review_count > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-metal-400'} />
            </div>
          </div>
          <strong className={`stat-value block mt-1 truncate ${t.review_count > 0 ? 'text-amber-700 dark:text-amber-400' : 'text-metal-900 dark:text-white'}`}>
            {t.review_count} {t.review_count === 1 ? 'invoice' : 'invoices'}
          </strong>
        </div>
      </div>

      {/* Table & Filters Card */}
      <Card noPadding className="overflow-hidden">
        {/* Filter Toolbar */}
        <div className="p-4 border-b border-metal-100 dark:border-metal-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-white dark:bg-metal-900">
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
            <Filter size={14} className="text-metal-400 shrink-0 hidden sm:inline mr-1" />
            {(['ALL', 'RECEIVABLE', 'PAYABLE', 'REVIEW'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setFilter(mode)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0 ${
                  filter === mode
                    ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-xs'
                    : 'bg-metal-100 dark:bg-metal-800 text-metal-600 dark:text-metal-300 hover:bg-metal-200 dark:hover:bg-metal-700'
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
            <Search size={14} className="absolute left-3 top-2.5 text-metal-400" />
            <input
              type="text"
              placeholder="Filter by party or invoice..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-3 py-1.5 rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-xs w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 text-metal-900 dark:text-white"
            />
          </div>
        </div>

        {query.data.items.length === 0 ? (
          <div className="p-12 text-center text-xs text-metal-500 space-y-2">
            <FileSpreadsheet size={32} className="mx-auto text-metal-300 dark:text-metal-600 mb-1" />
            <p className="font-semibold text-metal-700 dark:text-metal-300">No ledger entries recorded yet.</p>
            <p className="text-metal-400 max-w-sm mx-auto">
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
              <tbody className="divide-y divide-metal-100 dark:divide-metal-800">
                {items.map((row) => (
                  <tr
                    key={row.id}
                    className={row.status === 'REVIEW' ? 'bg-amber-50/40 dark:bg-amber-950/20 hover:bg-amber-50/70' : 'hover:bg-metal-50/80 dark:hover:bg-metal-800/50'}
                  >
                    <td className="font-semibold text-metal-900 dark:text-white">{row.party}</td>
                    <td className="font-mono text-xs text-metal-700 dark:text-metal-300">{row.invoice_number}</td>
                    <td className="text-metal-600 dark:text-metal-400 text-xs">{row.due_date}</td>
                    <td className="font-bold text-metal-900 dark:text-white">{formatPaiseINR(row.amount_paise)}</td>
                    <td>
                      <span
                        title={row.status}
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                          row.status === 'PAID'
                            ? 'bg-primary-50 text-primary-700 dark:bg-primary-950/50 dark:text-primary-300 border border-primary-200 dark:border-primary-800'
                            : row.status === 'REVIEW'
                            ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300 border border-amber-300 dark:border-amber-700 font-bold'
                            : 'bg-metal-100 text-metal-800 dark:bg-metal-800 dark:text-metal-200 border border-metal-200 dark:border-metal-700'
                        }`}
                      >
                        {row.status === 'PAID' && <CheckCircle2 size={11} />}
                        {row.status === 'REVIEW' && <AlertCircle size={11} />}
                        {formatEnumLabel(row.status)}
                      </span>
                      {row.status === 'REVIEW' && (
                        <button
                          className="ml-2 inline-flex items-center gap-0.5 text-xs text-primary-600 dark:text-primary-400 font-semibold underline hover:text-primary-800 dark:hover:text-primary-300"
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
                        <summary className="cursor-pointer text-xs font-medium text-metal-500 hover:text-primary-600 dark:text-metal-400 transition-colors">
                          View source
                        </summary>
                        <pre className="max-w-xs whitespace-pre-wrap text-[10px] bg-metal-50 dark:bg-metal-800/80 p-2 rounded-lg mt-1 border border-metal-200 dark:border-metal-700 font-mono text-metal-700 dark:text-metal-300">
                          {row.source_location || 'No source quote'}
                        </pre>
                      </details>
                    </td>
                    <td>
                      {row.direction === 'RECEIVABLE' && row.status !== 'PAID' ? (
                        <Link
                          to="/operations/collections"
                          className="inline-flex items-center gap-1 text-xs font-semibold text-primary-600 dark:text-primary-400 underline hover:text-primary-800 dark:hover:text-primary-300"
                        >
                          Collections
                          <ExternalLink size={10} />
                        </Link>
                      ) : (
                        <span className="text-metal-300 dark:text-metal-600">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Obligations */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
          <h3 className="font-bold text-sm text-metal-900 dark:text-white tracking-tight">Obligations</h3>
        </div>
        {obligations.data?.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {obligations.data.map((row, index) => (
              <Card key={index} className="space-y-1">
                <span className="text-xs font-semibold text-metal-600 dark:text-metal-400">{String(row.label)}</span>
                <p className="text-base font-bold text-metal-900 dark:text-white">{formatPaiseINR(Number(row.amount_paise))}</p>
              </Card>
            ))}
          </div>
        ) : (
          <Card className="text-center text-xs text-metal-400 py-6">
            No obligations recorded.
          </Card>
        )}
      </div>
    </section>
  )
}
