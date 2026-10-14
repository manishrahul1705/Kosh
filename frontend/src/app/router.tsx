import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { RequireAuth } from '@/app/RequireAuth'
import { SellerProvider } from '@/app/SellerContext'
import { LoginPage } from '@/features/auth/LoginPage'
import { MyTendersPage } from '@/features/portal/MyTendersPage'
import { TenderDetailPage } from '@/features/portal/TenderDetailPage'
import { ProfilePage } from '@/features/profile/ProfilePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { TenderCashPage } from '@/features/kosh/TenderCashPage'
import { ReportsPage } from '@/features/kosh/ReportsPage'
import { RevenuePage } from '@/features/kosh/RevenuePage'
import { IntelligencePage } from '@/features/kosh/IntelligencePage'
import { OperationsPage } from '@/features/kosh/OperationsPage'
import { CollectionsPage } from '@/features/kosh/CollectionsPage'
import { CashPage } from '@/features/kosh/CashPage'
import { PlanPage } from '@/features/kosh/PlanPage'
import { ApprovalsPage } from '@/features/kosh/ApprovalsPage'
import { AuditPage } from '@/features/kosh/AuditPage'
import { ConnectPage } from '@/features/kosh/ConnectPage'
import { LedgerPage } from '@/features/kosh/LedgerPage'

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
      { path: 'operations/tender-to-cash', element: <TenderCashPage /> },
      { path: 'operations/tender-to-cash/:tenderId', element: <TenderCashPage /> },
      { path: 'operations/reports', element: <ReportsPage /> },
      { path: 'operations/revenue', element: <RevenuePage /> },
      { path: 'operations/customer-intelligence', element: <IntelligencePage /> },
      { path: 'operations', element: <OperationsPage /> },
      { path: 'operations/:module', element: <OperationsPage /> },
      { path: 'operations/collections', element: <CollectionsPage /> },
      { path: 'cash', element: <CashPage /> },
      { path: 'ledger', element: <LedgerPage /> },
      { path: 'plan', element: <PlanPage /> },
      { path: 'approvals', element: <ApprovalsPage /> },
      { path: 'audit', element: <AuditPage /> },
      { path: 'connect', element: <ConnectPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
