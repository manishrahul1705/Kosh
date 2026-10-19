import React from 'react'

export const SandboxBanner: React.FC<{ className?: string }> = ({ className = '' }) => (
  <aside
    role="status"
    aria-label="Sandbox execution notice"
    className={`rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/50 px-3 py-1.5 text-xs font-medium text-amber-900 dark:text-amber-200 flex items-center gap-2 mb-3 ${className}`}
  >
    <span aria-hidden="true" className="text-amber-700 dark:text-amber-400 font-bold text-sm">⚠</span>
    <span><strong>Sandbox mode</strong>: no real money moves</span>
  </aside>
)
