import React from 'react'
import { NavLink } from 'react-router-dom'
import { ListChecks, Building2, ChevronLeft, ChevronRight, Gem, Wallet, Route, ShieldCheck, History, Plug, BookOpen } from 'lucide-react'
import { clsx } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', icon: ListChecks, label: 'My Tenders', exact: true },
  { to: '/profile', icon: Building2, label: 'Seller Profile', exact: false },
]

const KOSH_ITEMS = [
  { to: '/modules', icon: Building2, label: 'Kosh modules' },
  { to: '/operations', icon: ListChecks, label: 'Operations' },
  { to: '/cash', icon: Wallet, label: 'Cash' },
  { to: '/ledger', icon: BookOpen, label: 'Ledger' },
  { to: '/plan', icon: Route, label: 'Plan' },
  { to: '/approvals', icon: ShieldCheck, label: 'Approvals' },
  { to: '/audit', icon: History, label: 'Audit' },
  { to: '/connect', icon: Plug, label: 'Connect' },
]

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed, onToggle }) => (
  <aside
    className={clsx(
      'fixed left-0 top-0 h-screen bg-[#0f1f3d] flex flex-col z-40 transition-all duration-200',
      collapsed ? 'w-14' : 'w-14 md:w-56'
    )}
    aria-label="Main navigation"
  >
    <div className="flex items-center gap-2.5 px-3.5 py-4 border-b border-white/10 shrink-0">
      <div className="bg-[#1e5aab] rounded-lg p-1.5 shrink-0">
        <Gem size={18} className="text-white" aria-hidden="true" />
      </div>
      {!collapsed && (
        <div className="hidden md:block min-w-0">
          <p className="text-white font-semibold text-sm leading-tight truncate">GeM Tender Intelligence</p>
          <p className="text-gray-400 text-xs truncate">Matched tenders for you</p>
        </div>
      )}
    </div>
    <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.exact}
          className={({ isActive }) =>
            clsx(
              'flex justify-center md:justify-start items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors',
              collapsed && 'justify-center',
              isActive ? 'bg-white/15 text-white' : 'text-gray-400 hover:bg-white/10 hover:text-white'
            )
          }
          title={collapsed ? item.label : undefined}
        >
          <item.icon size={16} aria-hidden={true} />
          {!collapsed && <span className="hidden md:inline truncate">{item.label}</span>}
        </NavLink>
      ))}
      {!collapsed && <p className="hidden md:block px-3 pt-5 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">Kosh</p>}
      {KOSH_ITEMS.map((item) => (
        <NavLink key={item.to} to={item.to}
          className={({ isActive }) => clsx(
            'flex justify-center md:justify-start items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors',
            collapsed && 'justify-center',
            isActive ? 'bg-white/15 text-white' : 'text-gray-400 hover:bg-white/10 hover:text-white'
          )}
          title={collapsed ? item.label : undefined}
        >
          <item.icon size={16} aria-hidden={true} />
          {!collapsed && <span className="hidden md:inline truncate">{item.label}</span>}
        </NavLink>
      ))}
    </nav>
    <button
      onClick={onToggle}
      className="flex items-center justify-center h-10 border-t border-white/10 text-gray-400 hover:text-white hover:bg-white/10"
      aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    >
      {collapsed ? <ChevronRight size={16} aria-hidden="true" /> : <ChevronLeft size={16} aria-hidden="true" />}
    </button>
  </aside>
)
