import React from 'react'
import { clsx } from '@/lib/utils'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'primary'

const variants: Record<BadgeVariant, string> = {
  default: 'bg-metal-100 text-metal-700 border-metal-200',
  success: 'bg-emerald-50 text-emerald-800 border-emerald-200 shadow-2xs',
  warning: 'bg-amber-50 text-amber-800 border-amber-200',
  error: 'bg-rose-50 text-rose-800 border-rose-200',
  info: 'bg-sky-50 text-sky-800 border-sky-200',
  neutral: 'bg-metal-100 text-metal-600 border-metal-200',
  primary: 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white border-transparent shadow-xs',
}

interface BadgeProps {
  children: React.ReactNode
  variant?: BadgeVariant
  className?: string
}

export const Badge: React.FC<BadgeProps> = ({ children, variant = 'default', className }) => (
  <span className={clsx('inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border', variants[variant], className)}>
    {children}
  </span>
)

export function statusVariant(status: string): BadgeVariant {
  const s = status.toLowerCase()
  if (['eligible', 'success', 'ongoing', 'active', 'complete', 'completed', 'valid', 'matched'].some(k => s.includes(k))) return 'success'
  if (['not_eligible', 'failed', 'closed', 'error', 'rejected', 'blocked'].some(k => s.includes(k))) return 'error'
  if (['review', 'partial', 'pending', 'needs', 'proposed', 'stale'].some(k => s.includes(k))) return 'warning'
  if (['incomplete', 'unknown'].some(k => s.includes(k))) return 'neutral'
  return 'info'
}
export default Badge
