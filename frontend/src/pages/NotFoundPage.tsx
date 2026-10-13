import React from 'react'
import { Link } from 'react-router-dom'
import { FileSearch } from 'lucide-react'

export const NotFoundPage: React.FC = () => (
  <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50 text-center px-4">
    <FileSearch size={64} className="text-gray-300 mb-6" />
    <h1 className="text-4xl font-bold text-gray-900 mb-2">404</h1>
    <p className="text-lg text-gray-600 mb-6">Page not found</p>
    <Link to="/" className="btn-primary">Return to My Tenders</Link>
  </div>
)
