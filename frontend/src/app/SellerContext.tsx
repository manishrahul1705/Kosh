import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { sellersApi, type SellerSummary } from '@/lib/api/sellers'

const KEY = 'gem.activeSeller'

interface SellerContextValue {
  sellers: SellerSummary[]
  activeSellerId: number | null
  setActiveSellerId: (id: number) => void
  loading: boolean
  error: unknown
}

const Ctx = createContext<SellerContextValue | null>(null)

/** Sellers the signed-in user is a member of (the backend returns only those). */
export const SellerProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['my-sellers'],
    queryFn: async () => {
      await sellersApi.provision()
      return sellersApi.list()
    },
  })
  const [activeSellerId, setActive] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem(KEY)
      return v ? Number(v) : null
    } catch {
      return null
    }
  })
  const sellers = useMemo(() => data ?? [], [data])

  useEffect(() => {
    if (sellers.length && !sellers.some((s) => s.id === activeSellerId)) {
      setActive((sellers.find(s => s.name === 'Meenakshi Precision Components') ?? sellers[0]).id)
    }
  }, [sellers, activeSellerId])

  const setActiveSellerId = (id: number) => {
    setActive(id)
    try {
      localStorage.setItem(KEY, String(id))
    } catch {
      /* preference only */
    }
  }

  return (
    <Ctx.Provider value={{ sellers, activeSellerId, setActiveSellerId, loading: isLoading, error }}>
      {children}
    </Ctx.Provider>
  )
}

export function useSeller(): SellerContextValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useSeller must be used inside SellerProvider')
  return v
}
