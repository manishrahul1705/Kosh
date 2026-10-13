import React from 'react'
import { Inbox } from 'lucide-react'

interface EmptyStateProps {
  title: string
  description?: string
  icon?: React.ReactNode
  action?: React.ReactNode
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, icon, action }) => (
  <div className="flex flex-col items-center justify-center py-16 text-center px-4">
    <div className="text-gray-300 mb-4">{icon ?? <Inbox size={48} />}</div>
    <h3 className="text-base font-semibold text-gray-700 mb-1">{title}</h3>
    {description && <p className="text-sm text-gray-500 max-w-sm">{description}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
)
