import { koshApi } from '@/lib/api/kosh'
import { KoshPlaceholderPage } from './KoshPlaceholderPage'

export const ApprovalsPage = () => (
  <KoshPlaceholderPage title="Approvals" stage={6} resource="approvals" load={koshApi.approvals} />
)
