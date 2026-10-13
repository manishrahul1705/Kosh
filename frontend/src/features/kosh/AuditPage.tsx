import { koshApi } from '@/lib/api/kosh'
import { KoshPlaceholderPage } from './KoshPlaceholderPage'

export const AuditPage = () => (
  <KoshPlaceholderPage title="Audit" stage={7} resource="audit" load={koshApi.audit} />
)
