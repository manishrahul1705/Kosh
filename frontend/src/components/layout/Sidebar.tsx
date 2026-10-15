import React from 'react'
import { NavLink } from 'react-router-dom'
import {
  ListChecks,
  Building2,
  ChevronLeft,
  ChevronRight,
  Gem,
  Wallet,
  Route,
  ShieldCheck,
  History,
  Plug,
  BookOpen,
  LayoutGrid,
  SlidersHorizontal,
  Clock,
  X,
  TrendingUp,
  BarChart3,
  FileText,
  Calculator,
} from 'lucide-react'
import { clsx } from '@/lib/utils'

const TENDER_ITEMS = [
  { to: '/', icon: ListChecks, label: 'My Tenders', exact: true },
  { to: '/profile', icon: Building2, label: 'Seller Profile', exact: false },
]

const FINANCE_JOURNEY_ITEMS = [
  { to: '/connect', icon: Plug, label: 'Connect' },
  { to: '/ledger', icon: BookOpen, label: 'Ledger' },
  { to: '/cash', icon: Wallet, label: 'Cash' },
  { to: '/plan', icon: Route, label: 'Plan' },
  { to: '/operations/collections', icon: Clock, label: 'Collections' },
  { to: '/approvals', icon: ShieldCheck, label: 'Approvals' },
  { to: '/audit', icon: History, label: 'Audit' },
]

const OPERATIONS_ITEMS = [
  { to: '/operations', icon: SlidersHorizontal, label: 'Operations' },
  { to: '/operations/tender-to-cash', icon: Calculator, label: 'Tender to cash' },
  { to: '/operations/customer-intelligence', icon: TrendingUp, label: 'Customer intelligence' },
  { to: '/operations/revenue', icon: BarChart3, label: 'Revenue signal' },
  { to: '/operations/reports', icon: FileText, label: 'Cash reports' },
  { to: '/modules', icon: LayoutGrid, label: 'Kosh modules' },
]

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  mobileOpen?: boolean
  onMobileClose?: () => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  collapsed,
  onToggle,
  mobileOpen = false,
  onMobileClose,
}) => {
  const content = (
    <aside
      className={clsx(
        'fixed left-0 top-0 h-screen bg-white border-r border-metal-200 flex flex-col z-40 transition-all duration-200 select-none shadow-sm',
        collapsed ? 'w-20' : 'w-68',
        mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
      )}
      aria-label="Main navigation"
    >
      {/* Brand Header */}
      <div className="bg-gradient-to-b from-emerald-50/70 via-green-50/30 to-white px-4 py-4 border-b border-metal-200 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-xl flex items-center justify-center text-white shadow-sm shadow-emerald-500/25 shrink-0">
            <Gem size={20} className="text-white" aria-hidden="true" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-metal-900 font-extrabold text-base tracking-tight truncate">Kosh</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                  SANDBOX
                </span>
              </div>
              <p className="text-metal-500 text-xs font-medium truncate">SME Finance Copilot</p>
            </div>
          )}
        </div>
        {mobileOpen && (
          <button
            onClick={onMobileClose}
            className="md:hidden p-1.5 rounded-lg text-metal-500 hover:text-metal-900 hover:bg-metal-100 transition-colors"
            aria-label="Close mobile navigation"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Navigation Sections */}
      <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-4 custom-scrollbar">
        {/* Core Owner Finance Journey */}
        <div>
          {!collapsed && (
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-metal-400">
              Finance Journey
            </p>
          )}
          <div className="space-y-1">
            {FINANCE_JOURNEY_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onMobileClose}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all duration-150',
                    collapsed ? 'justify-center' : 'justify-start',
                    isActive
                      ? 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white font-semibold shadow-md shadow-emerald-500/20'
                      : 'text-metal-700 hover:bg-emerald-50 hover:text-emerald-700'
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                {({ isActive }) => (
                  <>
                    <item.icon
                      size={18}
                      aria-hidden="true"
                      className={clsx('shrink-0', isActive ? 'text-white' : 'text-metal-500')}
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </div>

        {/* Business Operations */}
        <div>
          {!collapsed && (
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-metal-400">
              Operations & Modules
            </p>
          )}
          <div className="space-y-1">
            {OPERATIONS_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onMobileClose}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all duration-150',
                    collapsed ? 'justify-center' : 'justify-start',
                    isActive
                      ? 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white font-semibold shadow-md shadow-emerald-500/20'
                      : 'text-metal-700 hover:bg-emerald-50 hover:text-emerald-700'
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                {({ isActive }) => (
                  <>
                    <item.icon
                      size={18}
                      aria-hidden="true"
                      className={clsx('shrink-0', isActive ? 'text-white' : 'text-metal-500')}
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </div>

        {/* GeM Tenders Portal */}
        <div>
          {!collapsed && (
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-metal-400">
              GeM Portal
            </p>
          )}
          <div className="space-y-1">
            {TENDER_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                onClick={onMobileClose}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all duration-150',
                    collapsed ? 'justify-center' : 'justify-start',
                    isActive
                      ? 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white font-semibold shadow-md shadow-emerald-500/20'
                      : 'text-metal-700 hover:bg-emerald-50 hover:text-emerald-700'
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                {({ isActive }) => (
                  <>
                    <item.icon
                      size={18}
                      aria-hidden="true"
                      className={clsx('shrink-0', isActive ? 'text-white' : 'text-metal-500')}
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      {/* Footer Info & Collapse Toggle */}
      <div className="p-3 border-t border-metal-200 shrink-0 space-y-2">
        {!collapsed && (
          <div className="px-1 text-[11px] text-metal-400 leading-tight">
            <p className="font-semibold text-metal-600">Autom Squad</p>
            <p className="text-[10px]">Topic E • SME Finance Copilot</p>
          </div>
        )}
        <button
          onClick={onToggle}
          className="hidden md:flex items-center justify-center w-full h-8 rounded-lg text-metal-500 hover:text-metal-900 hover:bg-metal-100 transition-colors"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
    </aside>
  )

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-metal-950/50 z-30 md:hidden backdrop-blur-xs transition-opacity"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}
      {content}
    </>
  )
}
export default Sidebar
