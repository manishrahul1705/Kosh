import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { RequireAuth } from '@/app/RequireAuth'

function wrap(ui: React.ReactElement, path: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('routing', () => {
  it('renders NotFoundPage at unknown path', () => {
    wrap(<Routes><Route path="*" element={<NotFoundPage />} /></Routes>, '/does-not-exist')
    expect(screen.getByText('404')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Return to My Tenders' })).toBeInTheDocument()
  })

  it('redirects to sign-in when there is no session', () => {
    sessionStorage.clear()
    wrap(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequireAuth><p>secret</p></RequireAuth>} />
      </Routes>,
      '/'
    )
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })
})
