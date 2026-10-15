import React, { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { ChatDrawer } from '@/features/kosh/ChatDrawer'
import { Moon, Sun } from 'lucide-react'
import { Sidebar } from './Sidebar'
import { TopNav } from './TopNav'

export const AppLayout: React.FC = () => {
  const [dark, setDark] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const sidebarWidth = collapsed ? 64 : 240

  return (
    <div
      data-kosh-theme={dark ? 'dark' : 'light'}
      className="min-h-screen bg-slate-50 transition-colors duration-150"
      style={{ '--sidebar-width': `${sidebarWidth}px` } as React.CSSProperties}
    >
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />
      <TopNav
        sidebarWidth={sidebarWidth}
        onMenuToggle={() => setMobileOpen(!mobileOpen)}
      />
      <main className="pt-14 md:pl-[var(--sidebar-width)] min-h-screen transition-all duration-200">
        <div className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
          {/* Quick utility controls bar */}
          <div className="flex items-center justify-between gap-3 pb-2 border-b border-slate-200/80">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                Local Sandbox Environment
              </span>
            </div>
            <div className="flex items-center gap-2.5">
              <button
                aria-pressed={dark}
                onClick={() => setDark(!dark)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition-colors shadow-2xs"
              >
                {dark ? (
                  <>
                    <Sun size={13} className="text-amber-500" />
                    Use light theme
                  </>
                ) : (
                  <>
                    <Moon size={13} className="text-slate-600" />
                    Use dark theme
                  </>
                )}
              </button>
              <ChatDrawer />
            </div>
          </div>

          <Outlet />
        </div>
      </main>
    </div>
  )
}

