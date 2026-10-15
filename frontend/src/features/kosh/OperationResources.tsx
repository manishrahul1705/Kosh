import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Boxes,
  Users,
  Search,
  Upload,
  MessageSquare,
  Bot,
  Layers,
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  FileText,
  Smartphone,
  ChevronDown,
} from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'

type Field = {
  key: string
  label: string
  type?: string
  options?: string[]
  optional?: boolean
}

const fields: Record<string, Field[]> = {
  MATERIAL: [
    { key: 'material_code', label: 'Material code' },
    { key: 'quantity', label: 'Counted quantity', type: 'number' },
    { key: 'reorder_point', label: 'Reorder threshold', type: 'number' },
    { key: 'unit_cost_paise', label: 'Unit cost (paise)', type: 'number' },
    { key: 'quantity_unit', label: 'Unit', options: ['UNIT', 'KG', 'KWH'] },
    { key: 'supplier_id', label: 'Supplier', optional: true },
  ],
  INVENTORY: [
    { key: 'material_id', label: 'Material' },
    { key: 'quantity', label: 'New counted stock quantity', type: 'number' },
  ],
  QUOTE: [
    { key: 'rfq_draft_id', label: 'RFQ draft' },
    { key: 'supplier_id', label: 'Supplier' },
    { key: 'price_paise', label: 'Quoted unit price (paise)', type: 'number' },
    { key: 'lead_days', label: 'Documented delivery days', type: 'number', optional: true },
    { key: 'quality_score', label: 'Evidence quality score (0–1)', type: 'decimal', optional: true },
    { key: 'reliability_score', label: 'Evidence reliability score (0–1)', type: 'decimal', optional: true },
  ],
  SHIPMENT: [
    { key: 'purchase_order_id', label: 'Confirmed purchase order' },
    { key: 'expected_date', label: 'Expected delivery', type: 'date' },
  ],
  SHIPMENT_STEP: [
    { key: 'shipment_id', label: 'Shipment' },
    { key: 'milestone', label: 'Observed checkpoint', options: ['DISPATCHED', 'AT_HUB', 'DELIVERED', 'DELAYED'] },
    { key: 'observed_date', label: 'Observation date', type: 'date' },
    { key: 'documented_payment_date', label: 'Documented revised payment date (optional)', type: 'date', optional: true },
  ],
  GOAL: [
    { key: 'goal', label: 'Goal', options: ['CASH_BUFFER', 'COLLECTIONS', 'MARGIN'] },
    { key: 'target_paise', label: 'Target (paise)', type: 'number' },
    { key: 'due_date', label: 'Target date', type: 'date' },
  ],
  TASK: [
    { key: 'goal_id', label: 'Goal' },
    { key: 'assigned_role', label: 'Assigned team', options: ['OWNER', 'OPERATIONS', 'FINANCE'] },
    { key: 'due_date', label: 'Task due date', type: 'date' },
  ],
  KNOWLEDGE: [
    {
      key: 'topic',
      label: 'Topic',
      options: [
        'PAYMENT_TERMS',
        'PURCHASE_COST',
        'MATERIAL_PRICE',
        'GENERAL',
        'SOP',
        'PRICING_RULE',
        'SUPPLIER_POLICY',
        'MANUFACTURING_PROCEDURE',
      ],
    },
    { key: 'title', label: 'Evidence title', optional: true },
    { key: 'tags', label: 'Search tags (comma-separated)', type: 'csv', optional: true },
    { key: 'text', label: 'Evidence text (inert data)', type: 'textarea' },
  ],
  ONBOARDING: [
    { key: 'tracking_method', label: 'Current records', options: ['NOTEBOOK', 'SPREADSHEET', 'ERP'] },
    { key: 'maturity', label: 'Business tracking maturity', options: ['BEGINNER', 'GROWING', 'ADVANCED'] },
    { key: 'needs', label: 'Cash priorities', type: 'multiple', options: ['COLLECTIONS', 'INVENTORY', 'PRICING', 'SALES', 'REPORTS'] },
  ],
  MARKET_SIGNAL: [
    { key: 'material_code', label: 'Material code' },
    { key: 'category', label: 'Signal', options: ['COMMODITY', 'POWER_TARIFF', 'INDUSTRY_NEWS'] },
    { key: 'change_percent', label: 'Observed change (%)', type: 'decimal' },
    { key: 'observed_date', label: 'Observation date', type: 'date' },
    { key: 'headline', label: 'Source headline' },
  ],
  STRUCTURAL_RISK: [
    { key: 'material_id', label: 'Material' },
    { key: 'risk', label: 'Risk', options: ['SINGLE_SUPPLIER', 'PRICE_VOLATILITY', 'STOCKOUT'] },
    { key: 'observation', label: 'Evidence observation', type: 'textarea' },
  ],
}

const labels: Record<string, string> = {
  MATERIAL: 'Material / inventory buffer',
  INVENTORY: 'Stock adjustment',
  QUOTE: 'Supplier quote comparison',
  SHIPMENT: 'Shipment tracker',
  SHIPMENT_STEP: 'Shipment checkpoint',
  GOAL: 'Cash goal',
  TASK: 'Assigned task',
  KNOWLEDGE: 'Knowledge evidence',
  ONBOARDING: 'Onboarding wizard',
  MARKET_SIGNAL: 'Market / power / news observation',
  STRUCTURAL_RISK: 'Long-term structural risk',
}

export const BusinessFields = ({ data }: { data: Record<string, unknown> }) => (
  <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
    {Object.entries(data)
      .filter(([key]) => key !== 'pdf_base64')
      .map(([key, value]) => (
        <div key={key} className="flex flex-col">
          <dt className="font-semibold text-muted-foreground uppercase text-[10px] tracking-wider">
            {key.replace(/_/g, ' ')}
          </dt>
          <dd className="font-medium text-foreground break-words mt-0.5">
            {Array.isArray(value)
              ? value.map((v, i) => (
                  <span key={i}>
                    {typeof v === 'object'
                      ? Object.values(v as Record<string, unknown>).map(String).join(' · ')
                      : String(v)}
                    {i < value.length - 1 ? '; ' : ''}
                  </span>
                ))
              : value == null
              ? 'unknown'
              : typeof value === 'object'
              ? 'See related record'
              : String(value)}
          </dd>
        </div>
      ))}
  </dl>
)

export const OperationResources = () => {
  const { activeSellerId } = useSeller()
  const qc = useQueryClient()

  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<
    { id: number; status: string; evidence_ref: string; data: Record<string, unknown> }[]
  >([])
  const [contactName, setContactName] = useState('')
  const [contactKind, setContactKind] = useState('CUSTOMER')
  const [conversation, setConversation] = useState('')
  const [kind, setKind] = useState('MATERIAL')
  const [values, setValues] = useState<Record<string, string>>({})
  const [evidence, setEvidence] = useState('')
  const [message, setMessage] = useState('')
  const [csv, setCsv] = useState('')
  const [channel, setChannel] = useState('EMAIL')
  const [notificationParty, setNotificationParty] = useState('')

  const query = useQuery({
    queryKey: ['kosh', 'operations', activeSellerId],
    queryFn: () => koshApi.operations(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const messaging = useQuery({
    queryKey: ['kosh', 'messaging-status', activeSellerId],
    queryFn: () => koshApi.messagingStatus(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const dashboard = useQuery({
    queryKey: ['kosh', 'operations-dashboard', activeSellerId],
    queryFn: () => koshApi.operationDashboard(activeSellerId!),
    enabled: activeSellerId !== null,
  })

  const run = async (task: () => Promise<unknown>) => {
    try {
      const r = await task()
      setMessage(typeof r === 'object' ? 'Saved.' : 'Complete')
      await qc.invalidateQueries({ queryKey: ['kosh'] })
    } catch (error) {
      const e = error as { response?: { data?: { detail?: unknown } } }
      setMessage(JSON.stringify(e.response?.data?.detail ?? String(error)))
    }
  }

  const relation = (key: string) =>
    key === 'supplier_id'
      ? query.data?.counterparties.map((p) => ({ id: p.id, label: p.name }))
      : key === 'rfq_draft_id'
      ? query.data?.drafts
          ?.filter((d) => d.kind === 'RFQ_MESSAGE')
          .map((d) => ({ id: d.id, label: `RFQ ${d.id}` }))
      : query.data?.items
          .filter(
            (r) =>
              r.kind ===
              (({
                material_id: 'MATERIAL',
                purchase_order_id: 'PO',
                shipment_id: 'SHIPMENT',
                goal_id: 'GOAL',
              } as Record<string, string>)[key])
          )
          .map((r) => ({ id: r.id, label: `${r.kind} ${r.id} · ${r.evidence_ref}` }))

  const submit = () => {
    const payload: Record<string, unknown> = { kind, evidence_ref: evidence }
    for (const f of fields[kind]) {
      const value = values[f.key]
      if (!value && f.optional) continue
      payload[f.key] =
        f.type === 'number' || f.key.endsWith('_id')
          ? Number(value)
          : f.type === 'multiple' || f.type === 'csv'
          ? value.split(',')
          : value
    }
    return koshApi.operationResource(activeSellerId!, payload)
  }

  return (
    <section aria-label="Operational resources" className="space-y-8">
      {/* Header & Day Review Bar */}
      <div className="card space-y-4 bg-muted/20 border-border">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-foreground">
              Operational resources, workers and workflows
            </h2>
            <p className="text-xs text-muted-foreground mt-1 max-w-2xl leading-relaxed">
              Missing quote scores remain review-required. Source text is inert. Workflow outbound
              steps always pause for approval.
            </p>
          </div>
          <button
            disabled={query.data?.role === 'VIEWER'}
            onClick={() => void run(() => koshApi.demoOperations(activeSellerId!))}
            className="btn-primary self-start sm:self-auto inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold shadow-sm whitespace-nowrap disabled:opacity-50"
          >
            <Bot className="w-4 h-4 text-primary-200" />
            Run internal business-day review
          </button>
        </div>

        {message && (
          <div className="p-3 rounded-lg bg-primary-50 dark:bg-primary-950/40 border border-primary-200 dark:border-primary-800 text-primary-900 dark:text-primary-200 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-primary-600 dark:text-primary-400 shrink-0" />
            <p role="status">{message}</p>
          </div>
        )}
      </div>

      {/* Resource Intake Form */}
      {query.data?.role !== 'VIEWER' && (
        <div className="card space-y-5">
          <div className="flex items-center gap-2 pb-3 border-b border-metal-100 dark:border-metal-800">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <div>
              <h3 className="text-base font-semibold text-foreground">Propose Operational Resource</h3>
              <p className="text-xs text-muted-foreground">
                Document inventory buffers, quotes, milestones, cash goals and operational rules.
              </p>
            </div>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(submit)
            }}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Resource <span className="text-rose-600">*</span>
                </label>
                <select
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value)
                    setValues({})
                  }}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                >
                  {Object.keys(fields).map((k) => (
                    <option key={k} value={k}>
                      {labels[k]}
                    </option>
                  ))}
                </select>
              </div>

              {fields[kind].map((f) => {
                const v = values[f.key] ?? ''
                const change = (value: string) => setValues({ ...values, [f.key]: value })
                const options = f.options
                const choices = f.key.endsWith('_id') ? relation(f.key) : undefined

                return (
                  <div key={f.key} className={f.type === 'textarea' ? 'sm:col-span-2 lg:col-span-3' : ''}>
                    <label className="block text-xs font-semibold text-foreground mb-1.5">
                      {f.label} {!f.optional && <span className="text-rose-600">*</span>}
                    </label>

                    {options ? (
                      <select
                        required={!f.optional}
                        multiple={f.type === 'multiple'}
                        value={f.type === 'multiple' ? v.split(',') : v}
                        onChange={(e) =>
                          change(
                            f.type === 'multiple'
                              ? Array.from(e.target.selectedOptions)
                                  .map((o) => o.value)
                                  .join(',')
                              : e.target.value
                          )
                        }
                        className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                      >
                        {f.type !== 'multiple' && <option value="">Select option</option>}
                        {options.map((o) => (
                          <option key={o}>{o}</option>
                        ))}
                      </select>
                    ) : f.key.endsWith('_id') ? (
                      <select
                        required={!f.optional}
                        value={v}
                        onChange={(e) => change(e.target.value)}
                        className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                      >
                        <option value="">Select owned resource</option>
                        {choices?.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    ) : f.type === 'textarea' ? (
                      <textarea
                        required={!f.optional}
                        rows={3}
                        value={v}
                        onChange={(e) => change(e.target.value)}
                        className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                      />
                    ) : (
                      <input
                        required={!f.optional}
                        type={f.type === 'decimal' ? 'number' : f.type === 'csv' ? 'text' : f.type ?? 'text'}
                        step={f.type === 'decimal' ? 'any' : '1'}
                        value={v}
                        onChange={(e) => change(e.target.value)}
                        className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                      />
                    )}
                  </div>
                )
              })}

              <div className="sm:col-span-2 lg:col-span-3">
                <label className="block text-xs font-semibold text-foreground mb-1.5">
                  Evidence reference <span className="text-rose-600">*</span>
                </label>
                <input
                  required
                  placeholder="e.g. Stock count sheet Oct 2026, Signed quote #991"
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
                />
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button type="submit" className="btn-primary px-4 py-2 text-sm font-semibold">
                Propose resource
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Auxiliary Inputs Grid: CSV, Counterparty Registration, Conversation Ingestion */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* CSV Import */}
        {query.data?.role !== 'VIEWER' && (
          <div className="card space-y-3 p-4 border-border flex flex-col justify-between">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <Upload className="w-4 h-4 text-primary-600" />
                <h3 className="text-sm font-semibold text-foreground">
                  Material CSV import (proposals only)
                </h3>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Columns: material_code, quantity, reorder_point, unit_cost_paise.
              </p>
            </div>

            <div className="space-y-3 pt-2">
              <input
                type="file"
                accept=".csv"
                aria-label="Material CSV"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) void file.text().then(setCsv)
                }}
                className="block w-full text-xs text-muted-foreground file:mr-2 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-muted file:text-foreground hover:file:bg-muted/80 cursor-pointer"
              />
              <button
                disabled={!csv || !evidence}
                onClick={() => void run(() => koshApi.importMaterials(activeSellerId!, csv, evidence))}
                className="w-full btn-secondary text-xs font-medium py-2 disabled:opacity-50"
              >
                Import proposed material rows
              </button>
            </div>
          </div>
        )}

        {/* Counterparty Registration */}
        {query.data?.role === 'OWNER' && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(() =>
                koshApi.registerCounterparty(activeSellerId!, {
                  name: contactName,
                  kind: contactKind,
                  evidence_ref: evidence,
                })
              )
            }}
            className="card space-y-3 p-4 border-border flex flex-col justify-between"
          >
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 text-primary-600" />
                <h3 className="text-sm font-semibold text-foreground">
                  Customer / supplier registration
                </h3>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Register verified counterparty for sales, POs and RFQ workflows.
              </p>
            </div>

            <div className="space-y-2.5 pt-2">
              <div>
                <label className="block text-[11px] font-semibold text-foreground mb-1">Name</label>
                <input
                  required
                  placeholder="e.g. Bharat Heavy Forge Ltd"
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background focus:ring-1 focus:ring-primary-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-foreground mb-1">
                  Relationship
                </label>
                <select
                  value={contactKind}
                  onChange={(e) => setContactKind(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background focus:ring-1 focus:ring-primary-500"
                >
                  <option>CUSTOMER</option>
                  <option>SUPPLIER</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={!evidence}
                className="w-full btn-secondary text-xs font-medium py-2 disabled:opacity-50"
              >
                Register and open evidence-gathering mission
              </button>
            </div>
          </form>
        )}

        {/* Conversation Evidence */}
        {query.data?.role !== 'VIEWER' && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(() =>
                koshApi.recordConversation(activeSellerId!, {
                  counterparty_id: Number(notificationParty),
                  channel: 'WEB',
                  text: conversation,
                  evidence_ref: evidence,
                })
              )
            }}
            className="card space-y-3 p-4 border-border flex flex-col justify-between"
          >
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <MessageSquare className="w-4 h-4 text-primary-600" />
                <h3 className="text-sm font-semibold text-foreground">
                  Incoming conversation evidence
                </h3>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Select the counterparty below. Text extraction proposes facts only; it creates no intent.
              </p>
            </div>

            <div className="space-y-2.5 pt-2">
              <textarea
                required
                rows={2}
                placeholder="Paste verbatim customer / vendor message text..."
                value={conversation}
                onChange={(e) => setConversation(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background focus:ring-1 focus:ring-primary-500"
              />
              <button
                type="submit"
                disabled={!notificationParty || !evidence}
                className="w-full btn-secondary text-xs font-medium py-2 disabled:opacity-50"
              >
                Record untrusted conversation
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Deterministic Worker Roster */}
      <div className="card space-y-4">
        <div>
          <h3 className="text-base font-semibold text-foreground">Deterministic worker roster</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Specialized rule-bound autonomous workers inspect operations, pricing anomalies, collections and covenants.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {[
            'executive',
            'collections',
            'sales',
            'procurement',
            'supplier',
            'pricing',
            'market',
            'customer',
            'revenue',
            'reporting',
          ].map((agent) => (
            <button
              key={agent}
              disabled={query.data?.role === 'VIEWER'}
              onClick={() => void run(() => koshApi.runAgent(activeSellerId!, agent))}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-medium bg-card hover:bg-muted/50 text-foreground transition-colors disabled:opacity-50"
            >
              <Bot className="w-3.5 h-3.5 text-muted-foreground" />
              Review {agent}
            </button>
          ))}
        </div>
      </div>

      {/* Knowledge Evidence Search */}
      <div className="card space-y-4">
        <div>
          <h3 className="text-base font-semibold text-foreground">Knowledge evidence search</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Query inert business policy rules, terms, SOPs and supplier guidelines.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () =>
              setSearchResults((await koshApi.knowledgeSearch(activeSellerId!, search)).items)
            )
          }}
          className="flex flex-col sm:flex-row items-center gap-3"
        >
          <div className="relative w-full">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
            <input
              required
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search knowledge"
              placeholder="Search inert knowledge rules (e.g. payment terms, SOPs)..."
              className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
            />
          </div>
          <button type="submit" className="btn-primary px-4 py-2 text-sm font-semibold whitespace-nowrap">
            Search inert evidence
          </button>
        </form>

        {searchResults.length > 0 && (
          <div className="space-y-3 pt-2">
            {searchResults.map((r) => (
              <article key={r.id} className="p-3.5 rounded-xl border border-border bg-muted/20 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-foreground">
                    {r.status} · {r.evidence_ref}
                  </h4>
                  <span className="text-[11px] font-mono text-muted-foreground">ID #{r.id}</span>
                </div>
                <BusinessFields data={r.data} />
              </article>
            ))}
          </div>
        )}
      </div>

      {/* Internal Drafts & Approval-Paused Workflows */}
      {query.data?.drafts && query.data.drafts.length > 0 && (
        <div className="card space-y-4">
          <div>
            <h3 className="text-base font-semibold text-foreground">
              Internal drafts and approval-paused workflows
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Draft messages and structured workflows held in safety escrow until explicitly approved.
            </p>
          </div>

          <div className="space-y-3">
            {query.data?.drafts?.map((d) => (
              <div
                key={d.id}
                className="p-4 rounded-xl border border-border bg-card space-y-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-foreground">
                      {d.module} · {d.kind} #{d.id}
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full font-semibold bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                      {d.status}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground font-mono whitespace-pre-wrap">{d.body}</p>
                </div>

                {query.data?.role !== 'VIEWER' && (
                  <button
                    onClick={() => void run(() => koshApi.createWorkflow(activeSellerId!, d.id))}
                    className="self-start sm:self-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-foreground text-background text-xs font-semibold hover:opacity-90 transition-opacity whitespace-nowrap"
                  >
                    Create workflow from draft {d.id}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sandbox Notification Settings */}
      <div className="card space-y-4">
        <div>
          <h3 className="text-base font-semibold text-foreground">Notification Dispatch Controls</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Configure simulated sandbox messaging channels for counterparty notifications.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-foreground mb-1.5">
              Sandbox notification channel
            </label>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
            >
              <option>EMAIL</option>
              <option>WHATSAPP</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1.5">
              Notification counterparty
            </label>
            <select
              value={notificationParty}
              onChange={(e) => setNotificationParty(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-colors"
            >
              <option value="">Select counterparty</option>
              {query.data?.counterparties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Operational Resources Registry */}
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-bold text-foreground">Operational Resources Registry</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Active items, materials, inventory counts, checkpoints and assigned tasks.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {query.data?.items.map((r) => (
            <article
              key={r.id}
              className="card space-y-3 p-4 border-border bg-card hover:border-primary-300 dark:hover:border-primary-700 transition-colors"
            >
              <div className="flex items-center justify-between pb-2 border-b border-border/60">
                <h3 className="text-sm font-bold text-foreground">
                  {labels[r.kind] ?? r.kind} #{r.id} · {r.status}
                </h3>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                    r.status === 'CONFIRMED' || r.status === 'COMPLETED'
                      ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                      : r.status === 'PROPOSED'
                      ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800'
                      : 'bg-muted text-muted-foreground border border-border'
                  }`}
                >
                  {r.status}
                </span>
              </div>

              <p className="text-xs text-muted-foreground font-mono">
                Evidence: <span className="text-foreground">{r.evidence_ref}</span>
              </p>

              <div className="text-xs bg-muted/20 p-2.5 rounded-lg border border-border/50">
                <BusinessFields data={r.data} />
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-1">
                {query.data?.role === 'OWNER' &&
                  !['COMPLETED', 'EXECUTED', 'REJECTED', 'SUPERSEDED'].includes(r.status) && (
                    <button
                      disabled={!evidence}
                      onClick={() => void run(() => koshApi.rejectOperation(activeSellerId!, r.id, evidence))}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-400 text-xs font-medium hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors disabled:opacity-40"
                    >
                      Reject or cancel with evidence {r.id}
                    </button>
                  )}

                {query.data?.role === 'OWNER' && r.status === 'PROPOSED' && fields[r.kind] && (
                  <button
                    onClick={() => void run(() => koshApi.confirmResource(activeSellerId!, r.id))}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold transition-colors"
                  >
                    Confirm resource {r.id}
                  </button>
                )}

                {query.data?.role === 'OWNER' && r.kind === 'TASK' && r.status === 'CONFIRMED' && (
                  <button
                    disabled={!evidence}
                    onClick={() => void run(() => koshApi.completeTask(activeSellerId!, r.id, evidence))}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold transition-colors disabled:opacity-40"
                  >
                    Complete task with evidence
                  </button>
                )}

                {query.data?.role !== 'VIEWER' && r.kind === 'WORKFLOW' && (
                  <button
                    onClick={() => void run(() => koshApi.advanceWorkflow(activeSellerId!, r.id))}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  >
                    Check next workflow step {r.id}
                  </button>
                )}

                {query.data?.role !== 'VIEWER' && notificationParty && (
                  <button
                    onClick={() =>
                      void run(() =>
                        koshApi.notificationDraft(activeSellerId!, r.id, Number(notificationParty), channel)
                      )
                    }
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  >
                    Draft notification for {r.id}
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>

      {/* Messaging / Device Pairing Card */}
      <div className="card space-y-3 p-4 bg-muted/20 border-border">
        <div className="flex items-center gap-2">
          <Smartphone className="w-4 h-4 text-primary-600" />
          <h3 className="text-sm font-semibold text-foreground">Messaging / device pairing</h3>
        </div>
        <div className="text-xs space-y-1.5">
          <p className="font-semibold text-foreground">
            {messaging.data?.transport} · {messaging.data?.device_pairing}
          </p>
          <p className="text-muted-foreground">{messaging.data?.reason}</p>
          {messaging.data?.owner_command && (
            <code className="block p-2 rounded bg-background border border-border font-mono text-[11px] text-foreground mt-2">
              {messaging.data?.owner_command}
            </code>
          )}
        </div>
      </div>

      {/* Cash Impact & Executive Timeline Accordion */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-foreground">
              Cash impact and executive timeline
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Live operational roll-up metrics driving forecast adjustments.
            </p>
          </div>
          <Link
            to="/approvals"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-semibold text-foreground hover:bg-muted/50 transition-colors"
          >
            Approve / execute paused actions
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="space-y-2">
          {Object.entries(dashboard.data ?? {}).map(([name, value]) => (
            <details
              key={name}
              className="group p-3 rounded-xl border border-border bg-card [&_summary::-webkit-details-marker]:hidden"
            >
              <summary className="flex items-center justify-between cursor-pointer font-semibold text-xs text-foreground select-none">
                <span className="capitalize">{name.replace(/_/g, ' ')}</span>
                <ChevronDown className="w-4 h-4 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <div className="pt-3 mt-2 border-t border-border/50 text-xs">
                {Array.isArray(value) ? (
                  <div className="space-y-2">
                    {value.map((row, i) => (
                      <div key={i} className="p-2.5 rounded-lg bg-muted/20 border border-border/40">
                        <BusinessFields data={row as Record<string, unknown>} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-muted-foreground">{String(value)}</p>
                )}
              </div>
            </details>
          ))}
        </div>
      </div>
    </section>
  )
}
