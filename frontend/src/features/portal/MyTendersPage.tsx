import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, RefreshCw, FileText, CheckCircle2, Clock, AlertCircle } from 'lucide-react'
import { portalApi, type TenderFilters } from '@/lib/api/portal'
import { useSeller } from '@/app/SellerContext'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
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
  <div className="stat-card">
    <p className="stat-label">{label}</p>
    <p className={`stat-value block mt-1 ${tone ?? 'text-metal-900 dark:text-white'}`}>{value}</p>
  </div>
)

export const MyTendersPage: React.FC = () => {
  const { activeSellerId, loading: sellersLoading, sellers, error: sellerError } = useSeller()
  const [filters, setFilters] = useState<TenderFilters>({ view: 'actionable', live_only: true, page: 1, page_size: 20 })
  const [search, setSearch] = useState('')
  const qc = useQueryClient()
  const refresh = useMutation({
    mutationFn: () => portalApi.refreshMatches(activeSellerId!),
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-metal-200/80 dark:border-metal-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">GeM Tenders</h2>
          </div>
          <p className="text-xs sm:text-sm text-metal-600 dark:text-metal-400 mt-1 ml-3.5">
            Real-time matched opportunities from the Government e-Marketplace aligned with your business profile.
          </p>
        </div>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <Link to="/profile" className="text-xs font-semibold text-primary-600 dark:text-primary-400 hover:underline">
            Update profile
          </Link>
          <Button
            variant="secondary"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending || activeSellerId === null}
          >
            <RefreshCw size={13} className={refresh.isPending ? 'animate-spin' : ''} />
            {refresh.isPending ? 'Refreshing...' : 'Refresh matches'}
          </Button>
        </div>
      </div>

      {summary.data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Tile label="Relevant open tenders" value={summary.data.live_matched + summary.data.live_review_required + summary.data.live_not_matched} />
            <Tile label="Matched open tenders" value={summary.data.live_matched} tone="text-primary-600 dark:text-primary-400" />
            <Tile label="Needs review" value={summary.data.live_review_required} tone="text-amber-700 dark:text-amber-400" />
            <Tile label="Closing within 3 days" value={summary.data.closing_within_3_days} tone={summary.data.closing_within_3_days > 0 ? 'text-rose-600 dark:text-rose-400' : undefined} />
            <Tile label="Last matched" value={summary.data.last_matched_at ? formatDate(summary.data.last_matched_at) : '—'} />
          </div>
          {summary.data.guidance?.map((g) => (
            <p key={g} className="text-xs bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 rounded-xl p-3.5">
              Add your products or categories to find relevant tenders.{' '}
              <Link to="/profile" className="font-semibold underline">Update profile</Link>
            </p>
          ))}
        </>
      )}

      {refresh.isError && <ErrorAlert message="Matches could not be refreshed. If you just refreshed, wait a moment and try again." />}
      {summary.error && <ErrorAlert message="Could not load your tender overview." onRetry={() => summary.refetch()} />}

      {/* Filter and Search Bar */}
      <Card noPadding className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => set({ view: v.key })}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                  filters.view === v.key
                    ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-xs'
                    : 'bg-metal-100 dark:bg-metal-800 text-metal-700 dark:text-metal-300 hover:bg-metal-200 dark:hover:bg-metal-700'
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>

          <form
            className="flex items-center gap-2 relative w-full sm:w-auto"
            onSubmit={(e) => {
              e.preventDefault()
              set({ q: search || undefined })
            }}
          >
            <Search size={14} className="absolute left-3 text-metal-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search bid no. or title"
              className="pl-9 pr-3 py-1.5 text-xs rounded-xl border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white w-full sm:w-60 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
              maxLength={200}
            />
          </form>
        </div>

        <div className="flex items-center gap-4 pt-2 border-t border-metal-100 dark:border-metal-800 text-xs text-metal-600 dark:text-metal-400">
          <label className="flex items-center gap-1.5 cursor-pointer font-medium">
            <input
              type="checkbox"
              checked={filters.live_only ?? true}
              onChange={(e) => set({ live_only: e.target.checked })}
              className="rounded text-primary-600 focus:ring-primary-500"
            />
            Open only
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer font-medium">
            <input
              type="checkbox"
              checked={filters.closing_within_days !== undefined}
              onChange={(e) => set({ closing_within_days: e.target.checked ? 7 : undefined })}
              className="rounded text-primary-600 focus:ring-primary-500"
            />
            Closing within 7 days
          </label>
        </div>
      </Card>

      {list.isLoading && <PageLoader />}
      {list.error && <ErrorAlert message="Failed to load tenders." onRetry={() => list.refetch()} />}
      {list.data && list.data.items.length === 0 && (
        <EmptyState title="No tenders in this view"
                    description="Try another filter, check your product categories or refresh matches after document processing." />
      )}
      {list.data && list.data.items.length > 0 && (
        <Card noPadding className="overflow-hidden">
          <div className="table-container border-0 shadow-none rounded-none">
            <table>
              <thead>
                <tr>
                  <th>Tender</th>
                  <th>Buyer</th>
                  <th>Bid end</th>
                  <th>Status</th>
                  <th>Match</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-metal-100 dark:divide-metal-800">
                {list.data?.items?.map((t) => (
                  <tr key={t.tender_id} className="hover:bg-metal-50/80 dark:hover:bg-metal-800/50">
                    <td className="py-3">
                      <Link to={`/tenders/${t.tender_id}`} className="font-bold text-primary-600 dark:text-primary-400 hover:underline">
                        {t.bid_number}
                      </Link>
                      <p className="text-metal-700 dark:text-metal-300 text-xs mt-0.5">{truncate(t.title, 90)}</p>
                      <p className="text-[11px] text-metal-400 mt-0.5">{t.category}</p>
                      {t.quantity !== null && <p className="text-[11px] text-metal-500">Quantity: {t.quantity}</p>}
                    </td>
                    <td className="text-metal-700 dark:text-metal-300 text-xs">{truncate(t.buyer_name ?? t.ministry, 50)}</td>
                    <td className="text-xs">
                      <span className="font-medium text-metal-900 dark:text-white">{formatDate(t.bid_end_at)}</span>
                      <p className="text-[11px] text-metal-400">{timeUntil(t.bid_end_at)}</p>
                    </td>
                    <td>
                      <Badge variant={STATUS_VARIANT[t.current_status]}>{t.current_status}</Badge>
                    </td>
                    <td>
                      <Badge variant={MATCH_VARIANT[t.match.match_status]}>{MATCH_LABEL[t.match.match_status]}</Badge>
                      <p className="text-[11px] text-metal-400 mt-1">
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
        </Card>
      )}
    </div>
  )
}
