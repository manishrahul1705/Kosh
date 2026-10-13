import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { getSession, signOut } from '@/lib/auth'
import { useSeller } from '@/app/SellerContext'

const TITLES: Record<string, string> = {
  '/': 'My Tenders',
  '/tenders': 'Tender Details',
  '/profile': 'Seller Profile',
  '/cash': 'Cash',
  '/plan': 'Plan',
  '/approvals': 'Approvals',
  '/audit': 'Audit',
  '/connect': 'Connect',
}

export const TopNav: React.FC<{ sidebarWidth: number }> = () => {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { sellers, activeSellerId, setActiveSellerId } = useSeller()
  const title = TITLES['/' + pathname.split('/')[1]] ?? 'GeM Tender Intelligence'

  const logout = () => {
    signOut()
    queryClient.clear()
    navigate('/login', { replace: true })
  }

  return (
    <header
      className="fixed left-14 md:left-[var(--sidebar-width)] top-0 right-0 h-14 bg-white border-b border-gray-200 flex items-center px-3 sm:px-5 gap-2 sm:gap-4 z-30"
    >
      <h1 className="text-base font-semibold text-gray-900 flex-1 truncate">{title}</h1>
      {sellers.length > 1 && (
        <select
          aria-label="Active seller"
          className="max-w-36 sm:max-w-xs text-sm border border-gray-300 rounded-md px-2 py-1"
          value={activeSellerId ?? ''}
          onChange={(e) => setActiveSellerId(Number(e.target.value))}
        >
          {sellers.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      )}
      <span className="hidden sm:block text-sm text-gray-600">{getSession()?.email}</span>
      <button onClick={logout} className="p-2 rounded-lg text-gray-500 hover:bg-gray-100" title="Sign out">
        <LogOut size={16} />
      </button>
    </header>
  )
}
