import React from 'react'
import { AlertTriangle, RotateCcw, Home, FileText } from 'lucide-react'

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Unhandled component error caught by ErrorBoundary:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-[400px] flex items-center justify-center p-6" role="alert">
          <div className="max-w-md w-full rounded-2xl border border-metal-200 dark:border-metal-800 bg-white dark:bg-metal-900 p-6 text-center space-y-4 shadow-metal">
            <div className="w-12 h-12 rounded-2xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800 text-amber-600 dark:text-amber-400 flex items-center justify-center mx-auto shadow-xs">
              <AlertTriangle size={24} />
            </div>

            <div className="space-y-1">
              <h2 className="text-lg font-bold text-metal-900 dark:text-white tracking-tight">Something went wrong</h2>
              <p className="text-xs text-metal-600 dark:text-metal-400 leading-relaxed">
                An unexpected error occurred while rendering this section. You can try recovering below.
              </p>
            </div>

            <div className="p-3 rounded-xl bg-metal-50 dark:bg-metal-800/60 border border-metal-200 dark:border-metal-700 text-left text-xs font-mono text-metal-700 dark:text-metal-300 overflow-x-auto max-h-32">
              {this.state.error?.message ?? 'Unknown component error'}
            </div>

            <div className="flex flex-wrap items-center justify-center gap-2.5 pt-1">
              <button
                className="btn-primary text-xs py-1.5 px-3.5 inline-flex items-center gap-1.5"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                <RotateCcw size={13} /> Try again
              </button>
              <a
                href="/"
                className="btn-secondary text-xs py-1.5 px-3.5 inline-flex items-center gap-1.5"
              >
                <Home size={13} /> Dashboard
              </a>
              <a
                href="/ledger"
                className="btn-secondary text-xs py-1.5 px-3.5 inline-flex items-center gap-1.5"
              >
                <FileText size={13} /> Ledger
              </a>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
