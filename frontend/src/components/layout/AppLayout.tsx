import React, { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { ChatDrawer } from '@/features/kosh/ChatDrawer'
import { Sidebar } from './Sidebar'
import { TopNav } from './TopNav'

export const AppLayout: React.FC = () => {
  const [dark,setDark]=useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const sidebarWidth = collapsed ? 56 : 224

  return (
    <div data-kosh-theme={dark?'dark':'light'} className="min-h-screen bg-gray-50" style={{ '--sidebar-width': `${sidebarWidth}px` } as React.CSSProperties}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <TopNav sidebarWidth={sidebarWidth} />
      <main
        className="pt-14 pl-14 md:pl-[var(--sidebar-width)] min-h-screen transition-all duration-200"
      >
        <div className="p-3 sm:p-6">
          <button aria-pressed={dark} onClick={()=>setDark(!dark)}>{dark?'Use light theme':'Use dark theme'}</button>
          <ChatDrawer />
          <Outlet />
        </div>
      </main>
    </div>
  )
}
