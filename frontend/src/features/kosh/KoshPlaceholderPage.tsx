import { useQuery } from '@tanstack/react-query'
import { useSeller } from '@/app/SellerContext'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'

interface Props {
  title: string
  stage: number
  resource: string
  load: (sellerId: number) => Promise<unknown>
}

export const KoshPlaceholderPage = ({ title, stage, resource, load }: Props) => {
  const { activeSellerId, loading } = useSeller()
  const query = useQuery({
    queryKey: ['kosh', resource, activeSellerId],
    queryFn: () => load(activeSellerId!),
    enabled: activeSellerId !== null,
  })
  if (loading || query.isLoading) return <PageLoader />
  return (
    <section aria-label={title}>
      <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
      {query.isError && <ErrorAlert message="Unable to load this business workspace." />}
      <EmptyState
        title={`Coming in Stage ${stage}`}
        description={activeSellerId === null ? 'Select a seller to open this workspace.' : 'This workspace is reserved for a future stage.'}
      />
    </section>
  )
}
