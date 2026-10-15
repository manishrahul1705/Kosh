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
    <header className="fixed left-0 md:left-[var(--sidebar-width)] top-0 right-0 h-16 bg-white/90 border-b border-metal-200 backdrop-blur-md flex items-center justify-between px-4 sm:px-6 z-30 transition-all duration-200 shadow-xs">
      <div className="flex items-center gap-3.5 min-w-0">
        <button
          onClick={onMenuToggle}
          className="md:hidden p-2 -ml-1 rounded-lg text-metal-600 hover:text-metal-900 hover:bg-metal-100 focus:outline-none"
          aria-label="Open mobile navigation"
        >
          <Menu size={20} />
        </button>

        {/* MetalliSense Green Section Marker */}
        <div className="w-1.5 h-7 bg-gradient-to-b from-primary-500 to-primary-600 rounded-full shadow-xs shrink-0 hidden sm:block" />

        <h1 className="text-sm sm:text-base font-bold text-metal-900 truncate tracking-tight">
          {title}
        </h1>
      </div>

      <div className="flex items-center gap-2.5 sm:gap-3 shrink-0">
        {sellers.length > 1 && (
          <div className="flex items-center gap-1.5 bg-metal-50 rounded-lg px-2.5 py-1.5 border border-metal-200">
            <Building size={14} className="text-metal-500 shrink-0 hidden sm:inline" />
            <select
              aria-label="Active seller"
              className="text-xs sm:text-sm font-medium text-metal-800 bg-transparent border-none focus:outline-none cursor-pointer max-w-32 sm:max-w-xs truncate"
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

        <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-metal-50 border border-metal-200">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center text-white font-bold text-xs shadow-2xs">
            {initial}
          </div>
          <span className="hidden sm:inline text-xs font-medium text-metal-700 truncate max-w-[140px]">
            {userEmail}
          </span>
        </div>

        <button
          onClick={logout}
          className="p-2 rounded-lg text-metal-500 hover:text-rose-600 hover:bg-rose-50 transition-colors"
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
