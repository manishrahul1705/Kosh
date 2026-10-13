import { koshApi } from '@/lib/api/kosh'
import { KoshPlaceholderPage } from './KoshPlaceholderPage'

export const CashPage = () => (
  <KoshPlaceholderPage title="Cash" stage={3} resource="ledger" load={koshApi.ledger} />
)
