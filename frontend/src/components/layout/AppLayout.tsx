import React, { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { ChatDrawer } from '@/features/kosh/ChatDrawer'
import { OnboardingTour } from '@/features/tour/OnboardingTour'
import { Moon, Sun, Compass } from 'lucide-react'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { useSeller } from '@/app/SellerContext'
import { Sidebar } from './Sidebar'
import { TopNav } from './TopNav'

export const AppLayout: React.FC = () => {
  const { activeSellerId } = useSeller()
  const [dark, setDark] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [tourOpen, setTourOpen] = useState(false)
  const sidebarWidth = collapsed ? 80 : 272

  return (
    <div
      data-kosh-theme={dark ? 'dark' : 'light'}
      className="min-h-screen bg-metal-50 text-metal-900 transition-colors duration-150 font-sans"
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
      <main className="pt-16 md:pl-[var(--sidebar-width)] min-h-screen transition-all duration-200">
        <div className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
          {/* Quick utility controls bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-metal-200">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 dark:bg-amber-950/50 text-amber-900 dark:text-amber-200 border border-amber-200 dark:border-amber-800 shadow-2xs">
                <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0 animate-pulse" />
                <span>Demo environment — no real money moves</span>
              </span>
              <span className="hidden md:inline text-xs text-metal-500 dark:text-metal-400 font-medium">
                Simulated financial workspace
              </span>
            </div>
            <div className="flex items-center gap-2.5">
              <button
                onClick={() => setTourOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-metal-200 bg-white text-metal-700 hover:bg-metal-50 hover:text-metal-900 transition-colors shadow-2xs cursor-pointer"
                title="Open guided showcase tour"
              >
                <Compass size={13} className="text-primary-600 dark:text-primary-400" />
                <span>Product Tour</span>
              </button>
              <button
                aria-pressed={dark}
                onClick={() => setDark(!dark)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-metal-200 bg-white text-metal-700 hover:bg-metal-50 hover:text-metal-900 transition-colors shadow-2xs cursor-pointer"
              >
                {dark ? (
                  <>
                    <Sun size={13} className="text-amber-500" />
                    Use light theme
                  </>
                ) : (
                  <>
                    <Moon size={13} className="text-metal-600" />
                    Use dark theme
                  </>
                )}
              </button>
              <ChatDrawer />
            </div>
          </div>

          <OnboardingTour open={tourOpen} onClose={() => setTourOpen(false)} workspaceId={activeSellerId} />

          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>

          {/* Unobtrusive footer */}
          <footer className="pt-8 pb-4 border-t border-metal-200 text-center text-xs text-metal-400">
            <p>
              Kosh — SME Finance Copilot • Built by <strong className="text-metal-600 font-semibold">Autom Squad</strong> for Hackathon Topic E
            </p>
          </footer>
        </div>
      </main>
    </div>
  )
}
export default AppLayout
