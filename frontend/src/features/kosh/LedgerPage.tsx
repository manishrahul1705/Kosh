import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
  if (!query.data) return <p className="text-gray-500">Select a seller to view ledger.</p>

  const t = query.data.totals
  const cards: [string, number | null | undefined, string?][] = [
    ['Open receivables', t.open_receivables_paise],
    ['Open payables (verified)', t.open_payables_paise],
    ['Overdue', t.overdue_receivables_paise],
    ['Bank balance', t.latest_bank_balance_paise],
  ]

  return (
    <section aria-label="Ledger" className="space-y-4">
      <SandboxBanner />
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Ledger & Invoices</h2>
        {t.bank_balance_as_of && (
          <span className="text-xs text-gray-500">
            Bank balance as of: <strong>{t.bank_balance_as_of}</strong>
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map(([label, value]) => (
          <div className="rounded border bg-white p-3" key={String(label)}>
            <p className="text-xs text-gray-500">{label}</p>
            <strong className="text-base text-gray-900">{formatPaiseINR(value as number | null)}</strong>
          </div>
        ))}
        <div className="rounded border bg-white p-3">
          <p className="text-xs text-gray-500">Review Required</p>
          <strong className={`text-base ${t.review_count > 0 ? 'text-amber-700' : 'text-gray-900'}`}>
            {t.review_count} {t.review_count === 1 ? 'invoice' : 'invoices'}
          </strong>
        </div>
      </div>

      {query.data.items.length === 0 ? (
        <div className="rounded border bg-gray-50 p-6 text-center text-sm text-gray-500">
          <p>No ledger entries recorded yet.</p>
          <p className="text-xs text-gray-400 mt-1">Connect your ERP or upload invoices on the Connect page to populate the ledger.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded border bg-white">
          <table className="w-full text-sm text-left">
            <thead className="border-b bg-gray-50 text-xs font-semibold text-gray-600">
              <tr>
                <th className="p-3">Party</th>
                <th className="p-3">Invoice</th>
                <th className="p-3">Due Date</th>
                <th className="p-3">Amount</th>
                <th className="p-3">Status</th>
                <th className="p-3">Evidence</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {query.data.items.map((row) => (
                <tr key={row.id} className={row.status === 'REVIEW' ? 'bg-amber-50/60' : 'hover:bg-gray-50'}>
                  <td className="p-3 font-medium text-gray-900">{row.party}</td>
                  <td className="p-3 text-gray-700">{row.invoice_number}</td>
                  <td className="p-3 text-gray-700">{row.due_date}</td>
                  <td className="p-3 font-semibold text-gray-900">{formatPaiseINR(row.amount_paise)}</td>
                  <td className="p-3">
                    <span
                      title={row.status}
                      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                        row.status === 'PAID'
                          ? 'bg-green-100 text-green-800'
                          : row.status === 'REVIEW'
                          ? 'bg-amber-100 text-amber-800 font-semibold'
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {formatEnumLabel(row.status)}
                    </span>
                    {row.status === 'REVIEW' && (
                      <button
                        className="ml-2 text-xs text-blue-600 underline font-medium hover:text-blue-800"
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
                  <td className="p-3">
                    <details>
                      <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-700">View source</summary>
                      <pre className="max-w-xs whitespace-pre-wrap text-[11px] bg-gray-50 p-2 rounded mt-1 border">
                        {row.source_location || 'No source quote'}
                      </pre>
                    </details>
                  </td>
                  <td className="p-3">
                    {row.direction === 'RECEIVABLE' && row.status !== 'PAID' ? (
                      <Link to="/operations/collections" className="text-xs text-blue-600 underline hover:text-blue-800">
                        Collections
                      </Link>
                    ) : (
                      '-'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="mt-6 font-semibold text-base text-gray-900">Obligations</h3>
      {obligations.data?.length ? (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {obligations.data.map((row, index) => (
            <li key={index} className="rounded border bg-white p-3 text-sm">
              <span className="font-medium text-gray-900">{String(row.label)}</span>
              <p className="text-xs text-gray-500 mt-1">{formatPaiseINR(Number(row.amount_paise))}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-gray-500">No obligations recorded.</p>
      )}
    </section>
  )
}
