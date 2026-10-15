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
  X,
} from 'lucide-react'
import { clsx } from '@/lib/utils'

const TENDER_ITEMS = [
  { to: '/', icon: ListChecks, label: 'My Tenders', exact: true },
  { to: '/profile', icon: Building2, label: 'Seller Profile', exact: false },
]

const JOURNEY_ITEMS = [
  { to: '/connect', icon: Plug, label: 'Connect' },
  { to: '/ledger', icon: BookOpen, label: 'Ledger' },
  { to: '/cash', icon: Wallet, label: 'Cash' },
  { to: '/plan', icon: Route, label: 'Plan' },
  { to: '/approvals', icon: ShieldCheck, label: 'Approvals' },
  { to: '/audit', icon: History, label: 'Audit' },
]

const OPS_ITEMS = [
  { to: '/operations', icon: SlidersHorizontal, label: 'Operations' },
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
        'fixed left-0 top-0 h-screen bg-[#0a1529] border-r border-slate-800 flex flex-col z-40 transition-all duration-200 select-none shadow-lg',
        collapsed ? 'w-16' : 'w-60',
        mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
      )}
      aria-label="Main navigation"
    >
      {/* Brand Header */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-slate-800/80 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="bg-gradient-to-br from-blue-500 to-indigo-700 rounded-lg p-2 shadow-sm shrink-0">
            <Gem size={18} className="text-white" aria-hidden="true" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-white font-bold text-sm tracking-tight truncate">Kosh</span>
                <span className="text-[10px] px-1.5 py-0.2 rounded font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                  SANDBOX
                </span>
              </div>
              <p className="text-slate-400 text-xs truncate">SME Finance Copilot</p>
            </div>
          )}
        </div>
        {mobileOpen && (
          <button
            onClick={onMobileClose}
            className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
            aria-label="Close mobile navigation"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Navigation Sections */}
      <nav className="flex-1 overflow-y-auto px-2.5 py-3 space-y-4">
        {/* Core Owner Journey */}
        <div>
          {!collapsed && (
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
              Finance Journey
            </p>
          )}
          <div className="space-y-0.5">
            {JOURNEY_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onMobileClose}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150',
                    collapsed ? 'justify-center' : 'justify-start',
                    isActive
                      ? 'bg-blue-600 text-white font-semibold shadow-xs'
                      : 'text-slate-300 hover:bg-slate-800/70 hover:text-white'
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                <item.icon size={16} aria-hidden="true" className="shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>
        </div>

        {/* Operations */}
        <div>
          {!collapsed && (
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
              Operations & Add-ons
            </p>
          )}
          <div className="space-y-0.5">
            {OPS_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onMobileClose}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150',
                    collapsed ? 'justify-center' : 'justify-start',
                    isActive
                      ? 'bg-blue-600 text-white font-semibold shadow-xs'
                      : 'text-slate-300 hover:bg-slate-800/70 hover:text-white'
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                <item.icon size={16} aria-hidden="true" className="shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>
        </div>

        {/* GeM Tenders */}
        <div>
          {!collapsed && (
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
              GeM Tenders
            </p>
          )}
          <div className="space-y-0.5">
            {TENDER_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                onClick={onMobileClose}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150',
                    collapsed ? 'justify-center' : 'justify-start',
                    isActive
                      ? 'bg-blue-600 text-white font-semibold shadow-xs'
                      : 'text-slate-300 hover:bg-slate-800/70 hover:text-white'
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                <item.icon size={16} aria-hidden="true" className="shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      {/* Collapse Toggle Footer */}
      <div className="p-2 border-t border-slate-800/80 shrink-0">
        <button
          onClick={onToggle}
          className="hidden md:flex items-center justify-center w-full h-8 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-colors"
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
          className="fixed inset-0 bg-slate-950/60 z-30 md:hidden backdrop-blur-xs transition-opacity"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}
      {content}
    </>
  )
}

