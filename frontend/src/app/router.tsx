import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { RequireAuth } from '@/app/RequireAuth'
import { SellerProvider } from '@/app/SellerContext'
import { LoginPage } from '@/features/auth/LoginPage'
import { MyTendersPage } from '@/features/portal/MyTendersPage'
import { TenderDetailPage } from '@/features/portal/TenderDetailPage'
import { ProfilePage } from '@/features/profile/ProfilePage'
import { NotFoundPage } from '@/pages/NotFoundPage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <SellerProvider>
          <AppLayout />
        </SellerProvider>
      </RequireAuth>
    ),
    children: [
      { index: true, element: <MyTendersPage /> },
      { path: 'tenders/:tenderId', element: <TenderDetailPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
