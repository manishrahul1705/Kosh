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
  '/operations': 'Operations Hub',
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

  const userEmail = getSession()?.email ?? ''
  const initial = userEmail ? userEmail.charAt(0).toUpperCase() : 'U'

  return (
    <header className="fixed left-0 md:left-[var(--sidebar-width)] top-0 right-0 h-16 bg-white/90 dark:bg-metal-900/90 border-b border-metal-200 dark:border-metal-800 backdrop-blur-md flex items-center justify-between px-3 sm:px-6 z-30 transition-all duration-200 shadow-xs">
      <div className="flex items-center gap-2 sm:gap-3.5 min-w-0 flex-1 mr-2">
        <button
          onClick={onMenuToggle}
          className="md:hidden p-1.5 -ml-1 rounded-lg text-metal-600 dark:text-metal-400 hover:text-metal-900 dark:hover:text-white hover:bg-metal-100 dark:hover:bg-metal-800 focus:outline-none shrink-0"
          aria-label="Open mobile navigation"
        >
          <Menu size={20} />
        </button>

        {/* MetalliSense Green Section Marker */}
        <div className="w-1.5 h-7 bg-gradient-to-b from-primary-500 to-primary-600 rounded-full shadow-xs shrink-0 hidden sm:block" />

        <h1 className="text-xs sm:text-base font-bold text-metal-900 dark:text-white truncate tracking-tight min-w-0">
          {title}
        </h1>
      </div>

      <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
        {sellers.length > 1 && (
          <div className="flex items-center gap-1 bg-metal-50 dark:bg-metal-800 rounded-lg px-2 sm:px-2.5 py-1 border border-metal-200 dark:border-metal-700 max-w-[110px] sm:max-w-xs">
            <Building size={13} className="text-metal-500 shrink-0 hidden sm:inline" />
            <select
              aria-label="Active seller"
              className="text-[11px] sm:text-xs font-medium text-metal-800 dark:text-metal-200 bg-transparent border-none focus:outline-none cursor-pointer w-full truncate"
              value={activeSellerId ?? ''}
              onChange={(e) => setActiveSellerId(Number(e.target.value))}
            >
              {sellers.map((s) => (
                <option key={s.id} value={s.id} className="dark:bg-metal-900">
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex items-center gap-2 px-1.5 sm:px-2.5 py-1 rounded-lg bg-metal-50 dark:bg-metal-800 border border-metal-200 dark:border-metal-700 shrink-0">
          <div className="w-6 h-6 sm:w-7 sm:h-7 rounded-full bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center text-white font-bold text-[11px] sm:text-xs shadow-2xs shrink-0">
            {initial}
          </div>
          <span className="hidden sm:inline text-xs font-medium text-metal-700 dark:text-metal-300 truncate max-w-[140px]">
            {userEmail}
          </span>
        </div>

        <button
          onClick={logout}
          className="p-1.5 sm:p-2 rounded-lg text-metal-500 dark:text-metal-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors shrink-0"
          title="Sign out"
          aria-label="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  )
}
export default TopNav
