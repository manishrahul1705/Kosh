import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { portalApi, type TenderFilters } from '@/lib/api/portal'
import { useSeller } from '@/app/SellerContext'
import { Badge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { Pagination } from '@/components/ui/Pagination'
import { formatDate, timeUntil, truncate } from '@/lib/utils'
import { MATCH_LABEL, MATCH_VARIANT, STATUS_VARIANT } from './labels'

const VIEWS: { key: NonNullable<TenderFilters['view']>; label: string }[] = [
  { key: 'actionable', label: 'Matched & review' },
  { key: 'matched', label: 'Matched' },
  { key: 'review', label: 'Needs review' },
  { key: 'not_matched', label: 'Not matched' },
]

const Tile: React.FC<{ label: string; value: number | string; tone?: string }> = ({ label, value, tone }) => (
  <div className="bg-white border border-gray-200 rounded-lg p-4">
    <p className="text-xs text-gray-500">{label}</p>
    <p className={`text-2xl font-semibold ${tone ?? 'text-gray-900'}`}>{value}</p>
  </div>
)

export const MyTendersPage: React.FC = () => {
  const { activeSellerId, loading: sellersLoading, sellers, error: sellerError } = useSeller()
  const [filters, setFilters] = useState<TenderFilters>({ view: 'actionable', live_only: true, page: 1, page_size: 20 })
  const [search, setSearch] = useState('')
  const qc = useQueryClient()
  const refresh = useMutation({ mutationFn: () => portalApi.refreshMatches(activeSellerId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-summary', activeSellerId] })
      qc.invalidateQueries({ queryKey: ['portal-tenders', activeSellerId] })
    },
  })

  const summary = useQuery({
    queryKey: ['portal-summary', activeSellerId],
    queryFn: () => portalApi.summary(activeSellerId!),
    enabled: activeSellerId !== null,
  })
  const list = useQuery({
    queryKey: ['portal-tenders', activeSellerId, filters],
    queryFn: () => portalApi.tenders(activeSellerId!, filters),
    enabled: activeSellerId !== null,
  })

  if (sellersLoading) return <PageLoader />
  if (sellerError) return <ErrorAlert message="Could not load your seller profiles." />
  if (!sellers.length)
    return <EmptyState title="No seller profile yet"
                       description="Your account is not linked to a seller profile. Ask your administrator to add you." />

  const set = (patch: Partial<TenderFilters>) => setFilters((f) => ({ ...f, page: 1, ...patch }))

  return (
    <div className="space-y-5">
      {summary.data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Tile label="Relevant open tenders" value={summary.data.live_matched + summary.data.live_review_required + summary.data.live_not_matched} />
            <Tile label="Matched open tenders" value={summary.data.live_matched} tone="text-green-700" />
            <Tile label="Needs review" value={summary.data.live_review_required} tone="text-amber-700" />
            <Tile label="Closing within 3 days" value={summary.data.closing_within_3_days} />
            <Tile label="Last matched" value={summary.data.last_matched_at ? formatDate(summary.data.last_matched_at) : '—'} />
          </div>
          {summary.data.guidance.map((g) => (
            <p key={g} className="text-sm bg-amber-50 text-amber-800 rounded-md p-3">Add your products or categories to find relevant tenders.{' '}
              <Link to="/profile" className="underline">Update profile</Link></p>
          ))}
        </>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <Link to="/profile" className="text-[#1e5aab] underline">View or update seller profile</Link>
        <button onClick={() => refresh.mutate()} disabled={refresh.isPending || activeSellerId === null}
          className="border border-gray-300 rounded-md px-3 py-1.5 disabled:opacity-50">{refresh.isPending ? 'Refreshing...' : 'Refresh matches'}</button>
      </div>
      {refresh.isError && <ErrorAlert message="Matches could not be refreshed. If you just refreshed, wait a moment and try again." />}
      {summary.error && <ErrorAlert message="Could not load your tender overview." onRetry={() => summary.refetch()} />}

      <div className="flex flex-wrap items-center gap-2">
        {VIEWS.map((v) => (
          <button key={v.key} onClick={() => set({ view: v.key })}
                  className={`px-3 py-1.5 rounded-md text-sm ${filters.view === v.key ? 'bg-[#1e5aab] text-white' : 'bg-white border border-gray-300 text-gray-700'}`}>
            {v.label}
          </button>
        ))}
        <label className="ml-2 text-sm flex items-center gap-1.5">
          <input type="checkbox" checked={filters.live_only ?? true} onChange={(e) => set({ live_only: e.target.checked })} />
          Open only
        </label>
        <label className="text-sm flex items-center gap-1.5">
          <input type="checkbox" checked={filters.closing_within_days !== undefined}
                 onChange={(e) => set({ closing_within_days: e.target.checked ? 7 : undefined })} />
          Closing within 7 days
        </label>
        <form className="ml-auto flex gap-2" onSubmit={(e) => { e.preventDefault(); set({ q: search || undefined }) }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search bid no. or title"
                 className="border border-gray-300 rounded-md px-3 py-1.5 text-sm" maxLength={200} />
        </form>
      </div>

      {list.isLoading && <PageLoader />}
      {list.error && <ErrorAlert message="Failed to load tenders." onRetry={() => list.refetch()} />}
      {list.data && list.data.items.length === 0 && (
        <EmptyState title="No tenders in this view"
                    description="Try another filter, check your product categories or refresh matches after document processing." />
      )}
      {list.data && list.data.items.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-left">
              <tr>
                <th className="px-4 py-2">Tender</th>
                <th className="px-4 py-2">Buyer</th>
                <th className="px-4 py-2">Bid end</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Match</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((t) => (
                <tr key={t.tender_id} className="border-t border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-2">
                    <Link to={`/tenders/${t.tender_id}`} className="font-medium text-[#1e5aab] hover:underline">{t.bid_number}</Link>
                    <p className="text-gray-600">{truncate(t.title, 90)}</p>
                    <p className="text-xs text-gray-400">{t.category}</p>
                    {t.quantity !== null && <p className="text-xs text-gray-500">Quantity: {t.quantity}</p>}
                  </td>
                  <td className="px-4 py-2 text-gray-700">{truncate(t.buyer_name ?? t.ministry, 50)}</td>
                  <td className="px-4 py-2">{formatDate(t.bid_end_at)}<p className="text-xs text-gray-500">{timeUntil(t.bid_end_at)}</p></td>
                  <td className="px-4 py-2"><Badge variant={STATUS_VARIANT[t.current_status]}>{t.current_status}</Badge></td>
                  <td className="px-4 py-2">
                    <Badge variant={MATCH_VARIANT[t.match.match_status]}>{MATCH_LABEL[t.match.match_status]}</Badge>
                    <p className="text-xs text-gray-500 mt-1">
                      {t.match.requirements_passed} met · {t.match.requirements_failed} failed · {t.match.requirements_needing_review} to review
                    </p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total}
                      page_size={list.data.page_size} onChange={(page) => setFilters((f) => ({ ...f, page }))} />
        </div>
      )}
    </div>
  )
}
