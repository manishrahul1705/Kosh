import React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, ExternalLink } from 'lucide-react'
import { portalApi, type Reason, type Requirement } from '@/lib/api/portal'
import { useSeller } from '@/app/SellerContext'
import { Badge } from '@/components/ui/Badge'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { formatCurrency, formatDate, timeUntil } from '@/lib/utils'
import { MATCH_LABEL, MATCH_HELP, MATCH_VARIANT, STATUS_VARIANT, friendlyLabel } from './labels'

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="bg-white border border-gray-200 rounded-lg p-5">
    <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide mb-3">{title}</h2>
    {children}
  </section>
)

const Field: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <dt className="text-xs text-gray-500">{label}</dt>
    <dd className="text-sm text-gray-900 break-words">{value ?? 'Not specified'}</dd>
  </div>
)

const ReasonList: React.FC<{ items: Reason[]; mark: string; tone: string; title: string }> = ({ items, mark, tone, title }) =>
  items.length ? (
    <div>
      <p className={`text-xs font-semibold uppercase ${tone}`}>{title}</p>
      <ul className="mt-1 space-y-1">
        {items.map((r, i) => (
          <li key={i} className="text-sm"><span className={tone}>{mark}</span> <b>{r.requirement}</b>
            {r.detail && <span className="text-gray-600"> — {r.detail}</span>}
            {r.relaxation_applied && <span className="text-gray-500"> (relaxation: {r.relaxation_applied})</span>}
          </li>
        ))}
      </ul>
    </div>
  ) : null

const Requirements: React.FC<{ items: Requirement[]; pending?: boolean }> = ({ items, pending }) =>
  items.length === 0 ? (
    <p className="text-sm text-gray-500">{pending ? 'Requirements are not available yet. Check package processing and review reasons.' : 'No requirements of this kind were found in the processed tender documents.'}</p>
  ) : (
    <ul className="space-y-3">
      {items.map((r, i) => (
        <li key={i} className="border-l-2 border-gray-200 pl-3">
          <p className="text-sm font-medium text-gray-900">
            {r.title}{' '}
            <Badge variant={r.obligation_level === 'MANDATORY' ? 'error' : 'neutral'}>{r.obligation_level}</Badge>
            {r.review_required && <Badge variant="warning" className="ml-1">Review</Badge>}
          </p>
          {(r.value_text || r.value_number !== null) && (
            <p className="text-sm text-gray-700">Value: {r.value_text ?? r.value_number} {r.unit ?? ''}</p>
          )}
          {r.summary && <p className="text-sm text-gray-600">{r.summary}</p>}
          {r.condition && <p className="text-sm text-gray-600">Applies when: {r.condition}</p>}
          {r.ambiguity && <p className="text-sm text-amber-700">Unclear: {r.ambiguity}</p>}
          {r.evidence.map((e, j) => (
            <blockquote key={j} className="mt-1 text-xs text-gray-500 bg-gray-50 rounded p-2">
              “{e.quote}” — {e.document_name ?? e.document_type ?? 'document'}
              {e.page != null && e.page > 0 ? `, page ${e.page}` : e.section ? `, ${e.section}` : ''}
              {e.source_location?.cell_range && `, cells ${e.source_location.cell_range.flat().filter(Boolean).join(' - ')}`}
            </blockquote>
          ))}
        </li>
      ))}
    </ul>
  )

export const TenderDetailPage: React.FC = () => {
  const { tenderId } = useParams()
  const { activeSellerId } = useSeller()
  const id = Number(tenderId)
  const q = useQuery({
    queryKey: ['portal-tender', activeSellerId, id],
    queryFn: () => portalApi.tender(activeSellerId!, id),
    enabled: activeSellerId !== null && Number.isFinite(id),
  })

  if (q.isLoading || activeSellerId === null) return <PageLoader />
  if (q.error || !q.data) return <ErrorAlert message="This tender is not available for your seller profile." />
  const d = q.data
  const m = d.match
  const fields = d.extracted_fields.filter(f => f.status === 'RESOLVED' &&
    !['bid_number', 'document_version_id', 'document_version_number', 'document_type'].includes(f.field))

  return (
    <div className="space-y-4 max-w-5xl">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-[#1e5aab]"><ArrowLeft size={14} /> My tenders</Link>

      <Section title="Basic information">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-lg font-semibold">{d.basic.bid_number}</span>
          <Badge variant={STATUS_VARIANT[d.status.current_status]}>{d.status.current_status}</Badge>
          {d.amendments.amended && <Badge variant="warning">Amended</Badge>}
          {d.basic.source_url && (
            <a href={d.basic.source_url} target="_blank" rel="noopener noreferrer"
               className="ml-auto text-sm inline-flex items-center gap-1 text-[#1e5aab]">View on GeM <ExternalLink size={12} /></a>
          )}
        </div>
        <p className="text-gray-800 mb-3">{d.basic.title ?? 'Title not specified'}</p>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <Field label="Buyer" value={d.basic.buyer_name} />
          <Field label="Ministry" value={d.basic.ministry} />
          <Field label="Department" value={d.basic.department} />
          <Field label="Category" value={d.basic.category} />
          <Field label="Quantity" value={d.basic.quantity} />
          <Field label="Estimated value" value={d.basic.estimated_value ? formatCurrency(d.basic.estimated_value) : null} />
          <Field label="Bid start" value={formatDate(d.basic.bid_start_at)} />
          <Field label="Bid end" value={`${formatDate(d.basic.bid_end_at)} (${timeUntil(d.basic.bid_end_at)})`} />
          <Field label="Opening" value={formatDate(d.basic.bid_opening_at)} />
          <Field label="Status checked" value={formatDate(d.status.last_status_check_at)} />
          <Field label="Last updated" value={formatDate(d.status.last_updated_at)} />
        </dl>
      </Section>

      <Section title="Your match">
        <div className="flex items-center gap-2 mb-3">
          <Badge variant={MATCH_VARIANT[m.match_status]}>{MATCH_LABEL[m.match_status]}</Badge>
          <span className="text-xs text-gray-500">Checked {formatDate(m.computed_at)}</span>
        </div>
        <div className="space-y-3">
          <p className="text-sm text-gray-600">{MATCH_HELP[m.match_status]}</p>
          <ReasonList items={m.reasons.matched} mark="✓" tone="text-green-700" title="Matched requirements" />
          <ReasonList items={m.reasons.failed} mark="✗" tone="text-red-700" title="Failed requirements" />
          <ReasonList items={m.reasons.needs_review} mark="?" tone="text-amber-700" title="Needs review" />
        </div>
      </Section>

      <Section title="What is this tender?">
        {d.package && <div className="mb-3 text-sm">
          <Badge variant={d.package.complete ? 'success' : 'warning'}>{d.package.complete ? 'Package complete' : 'Package incomplete'}</Badge>
          {!d.package.complete && <ul className="mt-2 text-amber-700">{d.package.reasons.map((r,i)=><li key={i}>{friendlyLabel(r.state)}</li>)}</ul>}
        </div>}
        {d.summary ? <p className="text-sm text-gray-800">{d.summary}</p> : (
          <p className="text-sm text-gray-600">AI summary is currently unavailable. Tender details, eligibility information and seller matching are available from the structured analysis.</p>
        )}
      </Section>

      {fields.length > 0 && <Section title="Structured tender details">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {fields.map(f => <Field key={f.field} label={friendlyLabel(f.field)}
            value={f.flag === 'TRUE' ? 'Yes' : f.flag === 'FALSE' ? 'No' : `${f.value ?? f.number ?? 'Not specified'}${f.unit ? ` ${f.unit}` : ''}`} />)}
        </dl>
      </Section>}

      {d.deterministic_requirements && <Section title="Structured eligibility">
        {d.deterministic_requirements.length ? <Requirements items={d.deterministic_requirements}/> : <p className="text-sm text-gray-500">No resolved structured requirements are available. Check package processing and review reasons above.</p>}
      </Section>}

      {d.eligibility.length > 0 && <Section title="Additional eligibility"><Requirements items={d.eligibility} /></Section>}
      {d.technical_requirements.length > 0 && <Section title="Technical requirements"><Requirements items={d.technical_requirements} /></Section>}
      {d.important_conditions.length > 0 && <Section title="Important conditions"><Requirements items={d.important_conditions} /></Section>}

      {d.review_flags.length > 0 && (
        <Section title="Points to review">
          <ul className="space-y-1">{d.review_flags.map((f, i) => (
            <li key={i} className="text-sm"><Badge variant="warning">{f.severity}</Badge> {f.message}</li>))}</ul>
        </Section>
      )}

      {d.amendments.amended && (
        <Section title="Amendments">
          <ul className="space-y-1 text-sm">
            {d.amendments.field_changes.map((c, i) => (
              <li key={i}>{c.field}: {c.old ?? '—'} → {c.new ?? '—'} <span className="text-gray-500">({formatDate(c.detected_at)})</span></li>))}
            {d.amendments.changed_documents.map((c) => (
              <li key={c.document_id}>{c.name ?? c.document_type}: {c.versions} version(s)</li>))}
          </ul>
        </Section>
      )}

      <Section title="Documents">
        <ul className="divide-y divide-gray-100">
          {d.documents.map((doc) => {
            const v = doc.versions.find((x) => x.version_id === doc.current_version_id) ?? doc.versions[doc.versions.length - 1]
            return (
              <li key={doc.document_id} className="py-3 flex flex-wrap items-center gap-3 text-sm">
                <Badge variant="info">{friendlyLabel(doc.document_type)}</Badge>
                <span className="flex-1 min-w-0 break-words">{doc.display_name ?? doc.filename ?? 'Document'}
                  {v && <span className="text-xs text-gray-500"> · v{v.version_number} · {v.file_type?.toUpperCase() ?? v.mime_type}
                    {' · '}{friendlyLabel(v.processing_state ?? v.validation_status)}
                    {v.extraction_state && ` · ${friendlyLabel(v.extraction_state)}`}
                    {v.extraction_error && ` · ${friendlyLabel(v.extraction_error)}`}
                  </span>}</span>
                {doc.source_url && <a href={doc.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#1e5aab]">Source <ExternalLink size={12} className="inline" /></a>}
                {!v && <span className="text-xs text-amber-700">{friendlyLabel(doc.processing_state ?? 'PENDING')}</span>}
                {v?.downloadable && (
                  <button className="inline-flex items-center gap-1 text-[#1e5aab]"
                          onClick={() => portalApi.downloadDocument(activeSellerId, id, doc.document_id, v.version_id,
                                                                    doc.filename ?? `document-${doc.document_id}.${v.file_type ?? 'bin'}`)}>
                    <Download size={14} /> Download
                  </button>
                )}
              </li>
            )
          })}
          {d.documents.length === 0 && <li className="text-sm text-gray-500 py-2">No documents collected yet.</li>}
        </ul>
      </Section>
    </div>
  )
}
