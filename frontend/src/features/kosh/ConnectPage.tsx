import { koshApi } from '@/lib/api/kosh'
import { KoshPlaceholderPage } from './KoshPlaceholderPage'

export const ConnectPage = () => (
  <KoshPlaceholderPage title="Connect" stage={1} resource="documents" load={koshApi.documents} />
)
