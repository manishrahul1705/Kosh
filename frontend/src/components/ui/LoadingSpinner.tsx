import React from 'react'

export const LoadingSpinner: React.FC<{ size?: number; className?: string }> = ({ size = 20, className = '' }) => (
  <svg
    className={`animate-spin ${className}`}
    width={size}
    height={size}
    fill="none"
    viewBox="0 0 24 24"
    aria-label="Loading"
  >
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
)

export const PageLoader: React.FC = () => (
  <div className="flex items-center justify-center min-h-[300px]">
    <LoadingSpinner size={32} className="text-[#1e5aab]" />
  </div>
)

export const SkeletonRow: React.FC<{ cols?: number }> = ({ cols = 5 }) => (
  <tr>
    {Array.from({ length: cols }).map((_, i) => (
      <td key={i} className="px-4 py-3">
        <div className="h-4 bg-gray-200 rounded animate-pulse" style={{ width: `${60 + (i * 17) % 40}%` }} />
      </td>
    ))}
  </tr>
)

export const CardSkeleton: React.FC = () => (
  <div className="card p-5 space-y-3 animate-pulse">
    <div className="h-4 bg-gray-200 rounded w-1/3" />
    <div className="h-8 bg-gray-100 rounded w-1/2" />
    <div className="h-3 bg-gray-200 rounded w-2/3" />
  </div>
)
