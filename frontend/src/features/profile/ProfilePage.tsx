import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sellersApi } from '@/lib/api/sellers'
import { portalApi } from '@/lib/api/portal'
import { toApiError } from '@/lib/api/client'
import { useSeller } from '@/app/SellerContext'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
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
    <div className="space-y-5 max-w-4xl">
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-lg font-semibold">{seller.data.name}</h2>
        <p className="text-xs text-gray-500">Profile revision {rev?.revision_number ?? '—'}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
        <h3 className="text-sm font-semibold uppercase text-gray-900">Matching profile</h3>
        <p className="text-sm text-gray-600">Each save creates a new profile revision and requests updated matches. If a recent refresh is still cooling down, refresh again shortly from My Tenders.</p>
        {message && <p role="status" className="text-sm bg-blue-50 text-blue-800 rounded p-2">{message}</p>}
        {EDITABLE.map((f) => (
          <form key={f.key} className="grid grid-cols-1 md:grid-cols-[220px_1fr_auto] gap-2 items-center"
                onSubmit={(e) => {
                  e.preventDefault()
                  const value = (values[activeSellerId]?.[f.key] ?? current(f.key)).trim()
                  if (value) save.mutate({ sellerId: activeSellerId, key: f.key, value_type: f.type, value })
                }}>
            <label htmlFor={f.key} className="text-sm text-gray-700">{f.label}</label>
            <input id={f.key} className="border border-gray-300 rounded-md px-3 py-1.5 text-sm" placeholder={f.hint}
                   type={f.type === 'NUMBER' ? 'number' : 'text'} min={f.type === 'NUMBER' ? 0 : undefined}
                   value={values[activeSellerId]?.[f.key] ?? current(f.key)}
                   onChange={(e) => setValues((v) => ({ ...v, [activeSellerId]: { ...v[activeSellerId], [f.key]: e.target.value } }))} />
            <Button type="submit" size="sm" variant="secondary" loading={save.isPending}>Save</Button>
          </form>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h3 className="text-sm font-semibold uppercase text-gray-900 mb-2">Documents on file</h3>
        {rev?.documents.length ? (
          <ul className="divide-y divide-gray-100">
            {rev.documents.map((d, i) => (
              <li key={i} className="py-2 text-sm flex items-center gap-2">
                <Badge variant="info">{d.document_type}</Badge>
                <span className="flex-1">{d.display_name}</span>
                <span className="text-xs text-gray-500">expires {formatDateOnly(d.expiry_date)}</span>
                <Badge variant={d.status === 'VERIFIED' ? 'success' : 'warning'}>{d.status}</Badge>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-gray-500">No documents recorded. Certificates such as ISO or OEM authorisation are needed to clear those requirements automatically.</p>}
      </div>
    </div>
  )
}
