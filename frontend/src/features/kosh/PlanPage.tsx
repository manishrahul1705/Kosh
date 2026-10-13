import { koshApi } from '@/lib/api/kosh'
import { KoshPlaceholderPage } from './KoshPlaceholderPage'

export const PlanPage = () => (
  <KoshPlaceholderPage title="Plan" stage={6} resource="plan" load={koshApi.plan} />
)
