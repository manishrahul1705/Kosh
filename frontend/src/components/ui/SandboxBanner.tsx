import React from 'react'

export const SandboxBanner: React.FC<{ className?: string }> = ({ className = '' }) => (
  <aside
    role="status"
    aria-label="Sandbox notification"
    className={`rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900 flex items-center gap-2 mb-3 ${className}`}
  >
    <span aria-hidden="true" className="text-amber-700 font-bold text-sm">⚠</span>
    <span><strong>SANDBOX</strong>: no real money moves</span>
  </aside>
)
