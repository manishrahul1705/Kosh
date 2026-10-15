import React from 'react'
import { useRouteError, isRouteErrorResponse, Link } from 'react-router-dom'
import { AlertTriangle, RotateCcw, Home, FileText } from 'lucide-react'

export const RouteErrorBoundary: React.FC = () => {
  const error = useRouteError()

  let errorMessage = 'An unexpected error occurred while rendering this view.'
  let errorStatus: number | null = null

  if (isRouteErrorResponse(error)) {
    errorStatus = error.status
    errorMessage = `${error.status} ${error.statusText}: ${error.data?.message || 'Page not found or request failed'}`
  } else if (error instanceof Error) {
    errorMessage = error.message
  } else if (typeof error === 'string') {
    errorMessage = error
  }

  return (
    <div className="min-h-[500px] flex items-center justify-center p-6" role="alert">
      <div className="max-w-lg w-full rounded-2xl border border-metal-200 dark:border-metal-800 bg-white dark:bg-metal-900 p-8 text-center space-y-5 shadow-metal">
        <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800 text-amber-600 dark:text-amber-400 flex items-center justify-center mx-auto shadow-xs">
          <AlertTriangle size={28} />
        </div>

        <div className="space-y-1.5">
          <h2 className="text-xl font-bold text-metal-900 dark:text-white tracking-tight">
            {errorStatus ? `Error ${errorStatus}` : 'Something went wrong'}
          </h2>
          <p className="text-xs text-metal-600 dark:text-metal-400 leading-relaxed">
            An unexpected error occurred while rendering this screen. You can reload the page, return to the overview, or inspect the cash ledger.
          </p>
        </div>

        <div className="p-3.5 rounded-xl bg-metal-50 dark:bg-metal-800/60 border border-metal-200 dark:border-metal-700 text-left text-xs font-mono text-metal-700 dark:text-metal-300 overflow-x-auto max-h-36">
          {errorMessage}
        </div>

        <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
          <button
            onClick={() => window.location.reload()}
            className="btn-primary text-xs py-2 px-4 inline-flex items-center gap-1.5"
          >
            <RotateCcw size={13} /> Reload page
          </button>
          <Link
            to="/"
            className="btn-secondary text-xs py-2 px-4 inline-flex items-center gap-1.5"
          >
            <Home size={13} /> Dashboard
          </Link>
          <Link
            to="/ledger"
            className="btn-secondary text-xs py-2 px-4 inline-flex items-center gap-1.5"
          >
            <FileText size={13} /> Cash Ledger
          </Link>
        </div>
      </div>
    </div>
  )
}
export default RouteErrorBoundary
