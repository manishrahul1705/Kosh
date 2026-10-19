import React from 'react'
import { Link } from 'react-router-dom'
import { FileSearch, ArrowLeft } from 'lucide-react'

export const NotFoundPage: React.FC = () => (
  <div className="flex flex-col items-center justify-center min-h-screen bg-[#f8fafb] dark:bg-metal-950 text-center px-4">
    <div className="w-16 h-16 rounded-2xl bg-metal-100 dark:bg-metal-800 flex items-center justify-center text-metal-400 mb-6 shadow-xs">
      <FileSearch size={32} />
    </div>
    <h1 className="text-4xl font-bold text-metal-900 dark:text-white mb-2 tracking-tight">404</h1>
    <p className="text-sm text-metal-500 mb-6 font-medium">Page not found in this workspace.</p>
    <Link to="/" className="btn-primary inline-flex items-center gap-2">
      <ArrowLeft size={14} />
      Return to My Tenders
    </Link>
  </div>
)
