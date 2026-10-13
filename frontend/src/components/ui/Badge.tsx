import React from 'react'
import { clsx } from '@/lib/utils'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'neutral'

const variants: Record<BadgeVariant, string> = {
  default: 'bg-gray-100 text-gray-700',
  success: 'bg-green-100 text-green-800',
  warning: 'bg-amber-100 text-amber-800',
  error: 'bg-red-100 text-red-800',
  info: 'bg-blue-100 text-blue-800',
  neutral: 'bg-gray-100 text-gray-600',
}

interface BadgeProps {
  children: React.ReactNode
  variant?: BadgeVariant
  className?: string
}

export const Badge: React.FC<BadgeProps> = ({ children, variant = 'default', className }) => (
  <span className={clsx('inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium', variants[variant], className)}>
    {children}
  </span>
)

export function statusVariant(status: string): BadgeVariant {
  const s = status.toLowerCase()
  if (['eligible', 'success', 'ongoing', 'active', 'complete', 'completed'].some(k => s.includes(k))) return 'success'
  if (['not_eligible', 'failed', 'closed', 'error'].some(k => s.includes(k))) return 'error'
  if (['review', 'partial', 'pending', 'needs'].some(k => s.includes(k))) return 'warning'
  if (['incomplete', 'unknown', 'blocked'].some(k => s.includes(k))) return 'neutral'
  return 'info'
}
