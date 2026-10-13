import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { getSession } from '@/lib/auth'

export const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation()
  if (!getSession()) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}
