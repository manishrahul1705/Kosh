import React from 'react'
import { clsx } from '@/lib/utils'

interface CardProps {
  title?: React.ReactNode
  subtitle?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
  headerClassName?: string
  bodyClassName?: string
  sectionMarker?: boolean
  noPadding?: boolean
}

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  actions,
  children,
  className = '',
  headerClassName = '',
  bodyClassName,
  sectionMarker = true,
  noPadding = false,
}) => {
  const resolvedBodyClassName = bodyClassName !== undefined
    ? bodyClassName
    : noPadding
    ? ''
    : 'p-5 sm:p-6'

  return (
    <div
      className={clsx(
        'bg-white dark:bg-metal-900 rounded-2xl shadow-metal border border-metal-200/80 dark:border-metal-800 transition-all duration-200',
        className
      )}
    >
      {title && (
        <div
          className={clsx(
            'px-5 py-4 border-b border-metal-100 dark:border-metal-800 flex flex-wrap justify-between items-center gap-3 bg-gradient-to-r from-metal-50/80 via-white to-transparent dark:from-metal-800/40 dark:via-metal-900 dark:to-transparent rounded-t-2xl',
            headerClassName
          )}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            {sectionMarker && (
              <div className="w-1.5 h-5 bg-gradient-to-b from-primary-500 to-primary-600 rounded-full shrink-0 shadow-xs" />
            )}
            <div className="min-w-0">
              <h3 className="text-sm sm:text-base font-bold text-metal-900 dark:text-white tracking-tight truncate">
                {title}
              </h3>
              {subtitle && (
                <p className="text-xs text-metal-500 dark:text-metal-400 font-normal truncate mt-0.5">
                  {subtitle}
                </p>
              )}
            </div>
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={resolvedBodyClassName}>{children}</div>
    </div>
  )
}
