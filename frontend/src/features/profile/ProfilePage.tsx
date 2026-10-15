import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, User, FileText, Shield } from 'lucide-react'
import { sellersApi } from '@/lib/api/sellers'
import { portalApi } from '@/lib/api/portal'
import { toApiError } from '@/lib/api/client'
import { useSeller } from '@/app/SellerContext'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { formatDateOnly } from '@/lib/utils'

const EDITABLE: { key: string; label: string; type: 'TEXT' | 'NUMBER' | 'BOOLEAN'; hint: string }[] = [
  { key: 'product_category', label: 'Products / categories', type: 'TEXT', hint: 'Comma-separated, e.g. Laptop, Desktop Computer' },
  { key: 'services', label: 'Services', type: 'TEXT', hint: 'Comma-separated, e.g. Manpower Outsourcing' },
  { key: 'keywords', label: 'Extra keywords', type: 'TEXT', hint: 'Comma-separated' },
  { key: 'annual_turnover', label: 'Annual turnover (INR)', type: 'NUMBER', hint: 'Latest audited figure' },
  { key: 'years_of_experience', label: 'Years of experience', type: 'NUMBER', hint: '' },
  { key: 'registered_state', label: 'Registered state', type: 'TEXT', hint: '' },
  { key: 'mse_status', label: 'MSE registered (TRUE/FALSE)', type: 'BOOLEAN', hint: '' },
  { key: 'startup_status', label: 'DPIIT startup (TRUE/FALSE)', type: 'BOOLEAN', hint: '' },
  { key: 'oem_authorized', label: 'OEM authorised (TRUE/FALSE)', type: 'BOOLEAN', hint: '' },
]

export const ProfilePage: React.FC = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()
  const [values, setValues] = useState<Record<number, Record<string, string>>>({})
  const [messages, setMessages] = useState<Record<number, string>>({})

  const seller = useQuery({
    queryKey: ['seller', activeSellerId],
    queryFn: () => sellersApi.get(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const save = useMutation({
    mutationFn: async (attr: { sellerId: number; key: string; value_type: 'TEXT' | 'NUMBER' | 'BOOLEAN'; value: string }) => {
      await sellersApi.setAttribute(attr.sellerId, attr)
      try {
        await portalApi.refreshMatches(attr.sellerId)
        return true
      } catch {
        return false // The profile was saved even when refresh is cooling down/unavailable.
      }
    },
    onSuccess: (refreshed, attr) => {
      setMessages(m => ({ ...m, [attr.sellerId]: refreshed ? 'Saved. Matches were recalculated for your profile.' : 'Profile saved. Refresh matches shortly to update the latest results.' }))
      qc.invalidateQueries({ queryKey: ['seller', attr.sellerId] })
      qc.invalidateQueries({ queryKey: ['portal-summary', attr.sellerId] })
      qc.invalidateQueries({ queryKey: ['portal-tenders', attr.sellerId] })
    },
    onError: (err, attr) => setMessages(m => ({ ...m, [attr.sellerId]: toApiError(err).message })),
  })

  if (activeSellerId === null || seller.isLoading) return <PageLoader />
  if (seller.error || !seller.data) return <ErrorAlert message="Failed to load seller profile." onRetry={() => seller.refetch()} />
  const rev = seller.data.active_revision
  const message = messages[activeSellerId]
  const current = (key: string) => {
    const a = rev?.attributes.find((x) => x.key === key)
    return a ? (a.value_text ?? a.value_json ?? (a.value_number !== null ? String(a.value_number) : '')) : ''
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <Card noPadding className="p-5 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-5 rounded-full bg-gradient-to-b from-primary-500 to-primary-600 shrink-0" />
            <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">{seller.data.name}</h2>
          </div>
          <p className="text-xs text-metal-500 mt-1 ml-3.5">Profile revision {rev?.revision_number ?? '—'}</p>
        </div>
        <Badge variant="success">Active Seller</Badge>
      </Card>

      <Card noPadding className="p-5 space-y-4">
        <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-3">
          <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wider text-metal-900 dark:text-white">Matching profile</h3>
            <p className="text-xs text-metal-500 mt-0.5">
              Each save creates a new profile revision and requests updated matches. If a recent refresh is still cooling down, refresh again shortly from My Tenders.
            </p>
          </div>
        </div>
        {message && (
          <p role="status" className="text-xs font-semibold bg-primary-50 dark:bg-primary-950/40 text-primary-800 dark:text-primary-200 border border-primary-200 dark:border-primary-800 rounded-xl p-3">
            {message}
          </p>
        )}
        <div className="space-y-3">
          {EDITABLE.map((f) => (
            <form key={f.key} className="grid grid-cols-1 md:grid-cols-[220px_1fr_auto] gap-2 items-center"
                  onSubmit={(e) => {
                    e.preventDefault()
                    const value = (values[activeSellerId]?.[f.key] ?? current(f.key)).trim()
                    if (value) save.mutate({ sellerId: activeSellerId, key: f.key, value_type: f.type, value })
                  }}>
              <label htmlFor={f.key} className="text-xs font-semibold text-metal-700 dark:text-metal-300">{f.label}</label>
              <input id={f.key} className="border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 rounded-xl px-3 py-1.5 text-xs text-metal-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500" placeholder={f.hint}
                     type={f.type === 'NUMBER' ? 'number' : 'text'} min={f.type === 'NUMBER' ? 0 : undefined}
                     value={values[activeSellerId]?.[f.key] ?? current(f.key)}
                     onChange={(e) => setValues((v) => ({ ...v, [activeSellerId]: { ...v[activeSellerId], [f.key]: e.target.value } }))} />
              <Button type="submit" size="sm" variant="secondary" loading={save.isPending}>Save</Button>
            </form>
          ))}
        </div>
      </Card>

      <Card noPadding className="p-5 space-y-3">
        <div className="flex items-center gap-2 border-b border-metal-100 dark:border-metal-800 pb-2.5">
          <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-metal-900 dark:text-white">Documents on file</h3>
        </div>
        {rev?.documents.length ? (
          <ul className="divide-y divide-metal-100 dark:divide-metal-800">
            {rev.documents.map((d, i) => (
              <li key={i} className="py-2.5 text-xs flex items-center gap-2">
                <Badge variant="info">{d.document_type}</Badge>
                <span className="flex-1 font-medium text-metal-900 dark:text-white">{d.display_name}</span>
                <span className="text-[11px] text-metal-400">expires {formatDateOnly(d.expiry_date)}</span>
                <Badge variant={d.status === 'VERIFIED' ? 'success' : 'warning'}>{d.status}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-metal-500 py-3">No documents recorded. Certificates such as ISO or OEM authorisation are needed to clear those requirements automatically.</p>
        )}
      </Card>
    </div>
  )
}
