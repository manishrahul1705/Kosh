import React from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

interface ErrorAlertProps {
  message: string
  onRetry?: () => void
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({ message, onRetry }) => (
  <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg p-4">
    <AlertCircle size={18} className="text-red-500 mt-0.5 shrink-0" />
    <div className="flex-1 min-w-0">
      <p className="text-sm font-medium text-red-800">Error</p>
      <p className="text-sm text-red-700 mt-0.5">{message}</p>
    </div>
    {onRetry && (
      <button onClick={onRetry} className="text-red-600 hover:text-red-800 shrink-0">
        <RefreshCw size={16} />
      </button>
    )}
  </div>
)

export const UnavailableModule: React.FC<{ feature: string; reason?: string }> = ({ feature, reason }) => (
  <div className="card p-8 text-center">
    <div className="text-amber-400 flex justify-center mb-3">
      <AlertCircle size={40} />
    </div>
    <h3 className="text-base font-semibold text-gray-800 mb-1">{feature} — Pending Integration</h3>
    <p className="text-sm text-gray-500">{reason ?? 'This module is not yet connected to a backend API.'}</p>
  </div>
)
