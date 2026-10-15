import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { LogOut, Menu, User, Building } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { getSession, signOut } from '@/lib/auth'
import { useSeller } from '@/app/SellerContext'

const TITLES: Record<string, string> = {
  '/': 'My Tenders',
  '/tenders': 'Tender Details',
  '/profile': 'Seller Profile',
  '/cash': 'Cash Forecast',
  '/ledger': 'Ledger & Invoices',
  '/plan': 'Financing Plan',
  '/approvals': 'Approvals & Actions',
  '/audit': 'Audit & Security',
  '/connect': 'Connect & Ingest',
  '/modules': 'Kosh Modules',
  '/operations': 'Operations',
  '/operations/collections': 'Collections & Statutory Interest',
  '/operations/customer-intelligence': 'Customer Intelligence',
  '/operations/revenue': 'Revenue Signal',
  '/operations/reports': 'Cash Reports Pack',
  '/operations/tender-to-cash': 'Tender to Cash',
}

interface TopNavProps {
  sidebarWidth: number
  onMenuToggle?: () => void
}

export const TopNav: React.FC<TopNavProps> = ({ onMenuToggle }) => {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { sellers, activeSellerId, setActiveSellerId } = useSeller()
  const title = TITLES[pathname] ?? TITLES['/' + pathname.split('/')[1]] ?? 'GeM Tender Intelligence'

  const logout = () => {
    signOut()
    queryClient.clear()
    navigate('/login', { replace: true })
  }

  return (
    <header className="fixed left-0 md:left-[var(--sidebar-width)] top-0 right-0 h-14 bg-white/95 border-b border-slate-200/90 backdrop-blur-xs flex items-center justify-between px-3 sm:px-6 z-30 transition-all duration-200 shadow-2xs">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onMenuToggle}
          className="md:hidden p-2 -ml-1 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 focus:outline-none"
          aria-label="Open mobile navigation"
        >
          <Menu size={18} />
        </button>
        <h1 className="text-sm sm:text-base font-bold text-slate-900 truncate tracking-tight">{title}</h1>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        {sellers.length > 1 && (
          <div className="flex items-center gap-1.5 bg-slate-100 rounded-lg px-2 py-1 border border-slate-200/80">
            <Building size={14} className="text-slate-500 shrink-0 hidden sm:inline" />
            <select
              aria-label="Active seller"
              className="text-xs sm:text-sm font-medium text-slate-800 bg-transparent border-none focus:outline-none cursor-pointer max-w-32 sm:max-w-xs truncate"
              value={activeSellerId ?? ''}
              onChange={(e) => setActiveSellerId(Number(e.target.value))}
            >
              {sellers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-600 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200/60">
          <User size={13} className="text-slate-400" />
          <span className="truncate max-w-[150px]">{getSession()?.email}</span>
        </div>

        <button
          onClick={logout}
          className="p-1.5 sm:p-2 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 transition-colors"
          title="Sign out"
          aria-label="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  )
}

