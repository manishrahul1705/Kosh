import { describe, it, expect, vi } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import type { ReactNode } from 'react'

vi.mock('@/lib/auth', async (original) => ({
  ...await original<typeof import('@/lib/auth')>(),
  getSession: () => ({ accessToken: 'test-session', refreshToken: '', expiresAt: Infinity, email: 'test@example.local' }),
}))
vi.mock('@/app/SellerContext', () => ({
  SellerProvider: ({ children }: { children: ReactNode }) => children,
  useSeller: () => ({ activeSellerId: 7, sellers: [{ id: 7, name: 'Test business' }], loading: false, error: null, setActiveSellerId: vi.fn() }),
}))
vi.mock('@/lib/api/kosh', () => ({
  koshApi: {
    messagingStatus:vi.fn().mockResolvedValue({transport:'SANDBOX_ONLY',device_pairing:'BLOCKED_OFFLINE',reason:'No external account linking',owner_command:''}),
    chat:vi.fn().mockResolvedValue({status:'REFUSED',reason:'Read-only cash chat cannot send payments.',facts:[]}),
    operations:vi.fn().mockResolvedValue({role:'OWNER',items:[],counterparties:[],drafts:[],market_sample:[]}),operationDashboard:vi.fn().mockResolvedValue({inventory:[],workflows:[],timeline:[]}),
    collections:vi.fn().mockResolvedValue({
      role:'OWNER',
      as_of:'2026-10-13',
      items:[],
      open_invoices:[{
        invoice_id:383,
        invoice_number:'INV-383',
        party:'ABC Industries',
        amount_paise:21553100,
        due_date:'2026-10-16',
        is_overdue:false,
        interest:{
          status:'REVIEW_REQUIRED',
          interest_paise:null,
          annual_rate:'0.1725',
          reason:'Acceptance date, agreement and MSE applicability require evidence.',
        },
        total_paise:21553100,
        terms:null,
      }],
      fixture:{
        label:'Fictional Overdue Statutory Interest Demonstration Fixture',
        note:'Separately labelled fictional fixture. Seeded ABC invoices are not overdue on 2026-10-13. Does not affect actual cash or ledger.',
        invoice_number:'FICT-DEMO-001',
        party:'Fictional Buyer Ltd',
        principal_paise:10000000,
        acceptance_date:'2026-01-01',
        agreement_status:'NONE',
        agreed_days:null,
        supplier_mse:true,
        evidence_ref:'fictional-demo:contract-clause-12',
        due_date:'2026-01-16',
        as_of:'2026-03-16',
        overdue_days:59,
        interest:{
          status:'COMPUTED',
          interest_paise:289566,
          annual_rate:'0.1725',
          monthly_rests:2,
          stub_days:0,
        },
        total_paise:10289566,
      },
    }),
    collectionTerms:vi.fn().mockResolvedValue({status:'DOCUMENTED'}),
    intelligence:vi.fn().mockResolvedValue({role:'OWNER',items:[],history:[]}),
    revenueSignal:vi.fn().mockResolvedValue({model:'Dependency-free level and trend',reason:'Optional estimated input',explainability:'Exact contributions',cash_timing:'Assumed payment delay',source:'Owned invoices',weeks:[]}),
    reports:vi.fn().mockResolvedValue({role:'OWNER',items:[],recipients:[]}),sharingConsents:vi.fn().mockResolvedValue({items:[]}),tenderCashList:vi.fn().mockResolvedValue({items:[]}),
    modules:vi.fn().mockResolvedValue({role:'OWNER',items:[{module:'sales',name:'Sales intake',cash_feed:'Expected receivables',href:'/operations/sales',enabled:true},{module:'collections',name:'Collections module',cash_feed:'Approved reminders',href:'/operations/collections',enabled:false}]}),toggleModule:vi.fn().mockResolvedValue({}),
    cashEvents:vi.fn().mockResolvedValue({role:'OWNER',items:[]}),
    ledger: vi.fn().mockResolvedValue({ seller_id: 7, totals: { open_receivables_paise:0,open_payables_paise:0,overdue_receivables_paise:0,review_count:0,latest_bank_balance_paise:null,bank_balance_as_of:null }, items: [] }),
    forecast: vi.fn().mockResolvedValue({seller_id:7,run:{id:1,as_of_date:'2026-10-13',buffer_paise:100000000,include_forecast_sales:true},weeks:[{week_index:1,week_start:'2026-10-12',week_end:'2026-10-18',p10_closing_balance_paise:80000000,p50_closing_balance_paise:120000000,p90_closing_balance_paise:150000000,expected_inflow_committed_paise:1,expected_inflow_forecast_paise:2,expected_outflow_committed_paise:3,expected_outflow_forecast_paise:4,prob_below_buffer:.6,expected_shortfall_paise:20000000}],under_review_paise:48000000,alert:{id:1,week_index:1,probability:.6,expected_shortfall_paise:20000000,peak_expected_shortfall_paise:20000000,causes:[{type:'CUSTOMER',customer:'ABC Industries',amount_paise:140000000,contribution_paise:10000000}],summary:'Week 1 warning'}}),
    analysis:vi.fn().mockResolvedValue({dso_days:60,dpo_days:42,cash_conversion_cycle_days:18,top_3_customer_share:.5}),backtest:vi.fn().mockResolvedValue({coverage_by_horizon:{'1':.8}}),runForecast:vi.fn(),whatIf:vi.fn(),acknowledgeAlert:vi.fn(),
    plan: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    financingOptions:vi.fn().mockResolvedValue({seller_id:7,sort_rule:'sorted by effective annual cost, lowest first; no provider pays for placement',items:[{product_id:'BANK_OD_DRAWDOWN',display_name:'Bank OD drawdown',provider_label:'Illustrative',scope:null,status:'MATCHED',max_amount_paise:180000000,amount_paise:180000000,days:90,cost_paise:7126027,cost_assumption:'Illustrative catalogue terms',effective_annual_rate:'.12',arrival_business_days:0,reasons:[{reason:'Criterion met.',reason_code:'CRITERION_MET',product_clause:{quote:'Current clause'}}],evidence:[],assumption:true,verify_before_relying:true}]}),
    safetyCurve:vi.fn().mockResolvedValue({items:[]}),
    latestPlan:vi.fn().mockResolvedValue({id:1,status:'PROPOSED',method:'LINPROG',why_this_plan:'Cheapest available capacity arriving before the alert.',total_cost_paise:100,baseline_cost_paise:1000,before_probabilities:[.8],after_probabilities:[.2],lines:[{id:1,product_id:'BANK_OD_DRAWDOWN',amount_paise:50000000,arrival_week:1,cost_paise:100,required_tier:'T3'}]}),createPlan:vi.fn(),evaluateFinancing:vi.fn(),
    actionInbox:vi.fn().mockResolvedValue({role:'OWNER',items:[]}),policy:vi.fn().mockResolvedValue({role:'OWNER',seller_kill:false,global_kill:false}),sandboxInbox:vi.fn().mockResolvedValue({items:[]}),sandboxOutbox:vi.fn().mockResolvedValue({items:[]}),executions:vi.fn().mockResolvedValue({items:[]}),killSwitch:vi.fn().mockResolvedValue({}),blockedDocumentPayment:vi.fn(),proposeIntent:vi.fn(),approveIntent:vi.fn(),rejectIntent:vi.fn(),requestOtp:vi.fn(),executeIntent:vi.fn(),
    approvals: vi.fn().mockResolvedValue({ seller_id: 7, status: 'NOT_IMPLEMENTED', items: [] }),
    audit: vi.fn().mockResolvedValue({ seller_id: 7, status: 'READY', items: [] }),
    documents: vi.fn().mockResolvedValue([]),
    consents: vi.fn().mockResolvedValue([]),
    securityEvents:vi.fn().mockResolvedValue({counts:{blocked_intents:0,failed_otps:0,token_replays:0,injection_detections:1}}),
    exportAudit:vi.fn().mockResolvedValue(""),verifyAuditExport:vi.fn(),
    verifyAudit: vi.fn().mockResolvedValue({valid:true,entries:0}),
    financingEvidence: vi.fn().mockResolvedValue({
      seller_id: 7,
      role: 'OWNER',
      as_of: '2026-10-13',
      evidence: {
        non_corporate: null,
        non_farm: null,
        income_generating: null,
        micro_small_enterprise: null,
        tarun_availed_and_repaid: null,
        udyam_certificate_present: null,
        gem_po_document: null,
        supplier_relationship_months: null,
        supplier_on_time_ratio: null,
        supplier_extension_status: 'UNKNOWN',
        evidence_ref: null,
        recorded_at: null,
      },
      sources: {},
      missing_criteria: [
        {
          product_id: 'MUDRA_LOAN',
          display_name: 'MUDRA loan',
          product_support_status: 'IMPLEMENTED',
          criteria: [
            { criterion: 'NON_CORPORATE', label: 'Non-corporate constitution', status: 'MISSING', value: null, evidence_required: 'Partnership deed / declaration', supported: true },
          ],
        },
      ],
      fixtures: [
        {
          id: 'FICT-MATCH-001',
          label: 'Legitimate Match (Mudra / CGTMSE)',
          description: 'Complete evidence satisfying all criteria',
          evidence: { non_corporate: true, non_farm: true },
        },
      ],
    }),
    saveFinancingEvidence: vi.fn().mockResolvedValue({ status: 'RECORDED' }),
    processDocument: vi.fn(),uploadDocument:vi.fn(),createConsent:vi.fn(),revokeConsent:vi.fn(),patchInvoice:vi.fn(),obligations:vi.fn().mockResolvedValue([]),
  },
}))

import { router } from '@/app/router'
import { koshApi } from '@/lib/api/kosh'

describe('Kosh protected routes', () => {
  it('keeps the ported theme control and read-only chat refusal',async()=>{
    await router.navigate('/cash')
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>)
    fireEvent.click(await screen.findByRole('button',{name:'Use dark theme'}))
    expect(screen.getByRole('button',{name:'Use light theme'})).toHaveAttribute('aria-pressed','true')
    fireEvent.click(screen.getByRole('button',{name:'Cash chat'}))
    fireEvent.change(screen.getByLabelText('Question'),{target:{value:'pay supplier X'}})
    fireEvent.click(screen.getByRole('button',{name:'Ask'}))
    await waitFor(()=>expect(koshApi.chat).toHaveBeenCalledWith(7,'pay supplier X'))
    expect(await screen.findByText(/REFUSED: Read-only cash chat/)).toBeInTheDocument()
    cleanup();client.clear()
  })
  it.each([
    ['/operations','Operations'],
    ['/operations/resources','Operations'],
    ['/operations/collections','Collections'],
    ['/operations/customer-intelligence','Customer intelligence'],
    ['/operations/revenue','Revenue signal'],
    ['/operations/reports','Cash reports'],
    ['/operations/tender-to-cash','Tender to cash'],
  ] as const)('renders the native port at %s',async(path,region)=>{
    await router.navigate(path)
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>)
    expect(await screen.findByRole('region',{name:region})).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'My Tenders'})).toBeInTheDocument()
    cleanup();client.clear()
  })

  it('lists disabled native modules and preserves all existing navigation', async () => {
    await router.navigate('/modules')
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>)
    expect(await screen.findByRole('region',{name:'Kosh modules'})).toBeInTheDocument()
    expect(await screen.findByRole('link',{name:'Collections module'})).toHaveAttribute('href','/operations/collections')
    expect(screen.getByRole('link',{name:'Sales intake'})).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'My Tenders'})).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'Seller Profile'})).toBeInTheDocument()
    const switches=screen.getAllByRole('checkbox');expect(switches).toHaveLength(2)
    fireEvent.click(switches[0]);await waitFor(()=>expect(koshApi.toggleModule).toHaveBeenCalledWith(7,'sales',false))
    cleanup();client.clear()
  })

  it('requires a T3 OTP, displays exact parameters and confirms owner kill changes', async () => {
    vi.mocked(koshApi.actionInbox).mockResolvedValue({role:'OWNER',items:[{id:'test-intent',plan_line_id:11,action_type:'TREDS_FINANCE',tier:'T3',params:{amount_paise:48000000,invoice_id:9},status:'PROPOSED',expires_at:null,policy_decision:{rule_ids:['ALLOWLIST']}}]})
    vi.mocked(koshApi.approveIntent).mockResolvedValueOnce({approval_token:'private-token',expires_at:new Date(Date.now()+300000).toISOString()})
    await router.navigate('/approvals')
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>)
    const approve=await screen.findByRole('button',{name:'Approve test-intent'})
    expect(approve).toBeDisabled()
    expect(screen.getByText(/48000000/)).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'Plan line 11'})).toHaveAttribute('href','/plan#plan-line-11')
    fireEvent.click(screen.getByRole('button',{name:'Request OTP'}))
    await waitFor(()=>expect(koshApi.requestOtp).toHaveBeenCalledWith(7,'test-intent'))
    fireEvent.change(screen.getByLabelText('OTP for test-intent'),{target:{value:'123456'}})
    await waitFor(()=>expect(approve).toBeEnabled())
    fireEvent.click(approve)
    await waitFor(()=>expect(koshApi.approveIntent).toHaveBeenCalledWith(7,'test-intent','123456'))
    expect(screen.queryByText('private-token')).not.toBeInTheDocument()
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button',{name:'Enable seller kill switch'}))
    expect(koshApi.killSwitch).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button',{name:'Enable seller kill switch'}))
    await waitFor(()=>expect(koshApi.killSwitch).toHaveBeenCalledWith(7,true))
    confirm.mockRestore();vi.mocked(koshApi.actionInbox).mockResolvedValue({role:'OWNER',items:[]});cleanup();client.clear()
  })
  it('does not offer approval or kill controls to a viewer', async () => {
    vi.mocked(koshApi.actionInbox).mockResolvedValueOnce({role:'VIEWER',items:[]})
    vi.mocked(koshApi.policy).mockResolvedValueOnce({role:'VIEWER',seller_kill:false,global_kill:false})
    await router.navigate('/approvals')
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>)
    await screen.findByText('No action intents.')
    expect(screen.queryByRole('button',{name:/seller kill switch/})).not.toBeInTheDocument()
    expect(screen.queryByRole('button',{name:'Test blocked document payment'})).not.toBeInTheDocument()
    cleanup();client.clear()
  })

  it('submits the owner selected safety target', async () => {
    await router.navigate('/plan')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
    const target = await screen.findByRole('combobox', { name: 'Plan safety target' })
    expect(target).toHaveValue('0.20')
    fireEvent.change(target, { target: { value: '0.30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Build plan' }))
    await waitFor(() => expect(koshApi.createPlan).toHaveBeenCalledWith(7, '0.30'))
    expect(screen.getByText('Safety vs cost')).toBeInTheDocument()
    cleanup()
    client.clear()
  })
  it.each([
    ['/cash','Cash forecast',koshApi.forecast],
    ['/ledger','Ledger',koshApi.ledger],
    ['/plan','Financing plan',koshApi.financingOptions],
    ['/approvals','Approvals',koshApi.actionInbox],
    ['/audit','Audit',koshApi.audit],
    ['/connect','Connect',koshApi.documents],
  ] as const)('renders protected Kosh route %s in the existing layout', async(path,title,load)=>{
    await router.navigate(path)
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>)
    expect(await screen.findByRole('region',{name:title})).toBeInTheDocument()
    expect(screen.getByRole('complementary',{name:'Main navigation'})).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'My Tenders'})).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'Seller Profile'})).toBeInTheDocument()
    await waitFor(()=>expect(load).toHaveBeenCalledWith(7))
    if(path==='/plan'){
      expect(screen.getByRole('columnheader',{name:'Days'})).toBeInTheDocument()
      expect(screen.getByRole('columnheader',{name:'Absolute cost'})).toBeInTheDocument()
      expect(screen.getByText('Cheapest available capacity arriving before the alert.')).toBeInTheDocument()
      expect(screen.getByText('Safety target not verified; build a new plan.')).toBeInTheDocument()
      expect(screen.getByText('NBFC baseline insufficient or not verified; savings unavailable.')).toBeInTheDocument()
      expect(screen.getByText('Proposed gap-closing plan')).toBeInTheDocument()
      expect(screen.getByText('Binding plan cost:')).toBeInTheDocument()
      expect(screen.getAllByText('Binding financing plan')[0]).toBeInTheDocument()
    }
    if(path==='/ledger'){
      expect(screen.getByText('Open receivables')).toBeInTheDocument()
      expect(screen.getByText('Open payables (verified)')).toBeInTheDocument()
      expect(screen.getByText('Held-for-review payables')).toBeInTheDocument()
      expect(screen.getByText('Review Required')).toBeInTheDocument()
    }
    if(path==='/audit'){
      expect(screen.getByRole('button',{name:'Export JSONL'})).toBeInTheDocument()
      expect(await screen.findByText('injection detections: 1')).toBeInTheDocument()
    }
    expect(screen.getByRole('link',{name:'Collections'})).toHaveAttribute('href','/operations/collections')
    cleanup();client.clear()
  })

  it('renders owner collections evidence form, overdue demonstration fixture, and submits terms', async () => {
    await router.navigate('/operations/collections')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)

    // 1. Fictional fixture demonstrated
    expect(await screen.findByText('Fictional Overdue Statutory Interest Demonstration Fixture')).toBeInTheDocument()
    expect(screen.getByText(/Demonstration Only/i)).toBeInTheDocument()
    expect(screen.getByText(/FICT-DEMO-001/i)).toBeInTheDocument()

    // 2. Calculation as-of date badge
    expect(screen.getByText('2026-10-13')).toBeInTheDocument()

    // 3. Open invoice displayed with REVIEW REQUIRED status and total
    expect(screen.getByText('INV-383')).toBeInTheDocument()
    expect(screen.getByText('ABC Industries')).toBeInTheDocument()
    expect(screen.getByText('REVIEW REQUIRED')).toBeInTheDocument()

    // 4. Owner form is present
    expect(screen.getByText('Document Invoice Evidence & Payment Terms')).toBeInTheDocument()
    const editBtn = screen.getByRole('button', { name: 'Edit evidence' })
    fireEvent.click(editBtn)

    // Fill the evidence form
    const termsSelect = screen.getByLabelText(/Payment terms/i)
    fireEvent.change(termsSelect, { target: { value: 'AGREED' } })

    const daysInput = screen.getByPlaceholderText(/e.g. 30/i)
    fireEvent.change(daysInput, { target: { value: '30' } })

    const mseSelect = screen.getByLabelText(/Micro\/Small enterprise applicability/i)
    fireEvent.change(mseSelect, { target: { value: 'APPLICABLE' } })

    const evidenceInput = screen.getByPlaceholderText(/e.g. PO clause 4.2/i)
    fireEvent.change(evidenceInput, { target: { value: 'PO-2026-ABC Clause 4' } })

    const saveBtn = screen.getByRole('button', { name: 'Save Documented Terms' })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(koshApi.collectionTerms).toHaveBeenCalledWith(7, 383, {
        acceptance_date: null,
        agreement_status: 'AGREED',
        agreed_days: 30,
        supplier_mse: true,
        evidence_ref: 'PO-2026-ABC Clause 4',
      })
    })

    cleanup()
    client.clear()
  })

  it('renders financing eligibility evidence workflow, missing criteria, and saves owner evidence', async () => {
    await router.navigate('/plan')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)

    expect(await screen.findByRole('region', { name: 'Financing eligibility evidence' })).toBeInTheDocument()
    expect(screen.getByText('Missing criteria across review options')).toBeInTheDocument()
    expect(screen.getByText('Non-corporate constitution')).toBeInTheDocument()

    // Test form editing
    const nonCorpSelect = screen.getByLabelText('Non-corporate constitution')
    fireEvent.change(nonCorpSelect, { target: { value: 'YES' } })

    const relMonthsInput = screen.getByLabelText('Supplier relationship tenure in months')
    fireEvent.change(relMonthsInput, { target: { value: '24' } })

    const refInput = screen.getByLabelText('Supporting evidence reference or note')
    fireEvent.change(refInput, { target: { value: 'Partnership deed verified' } })

    const saveBtn = screen.getByRole('button', { name: 'Save evidence' })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(koshApi.saveFinancingEvidence).toHaveBeenCalledWith(7, expect.objectContaining({
        non_corporate: true,
        supplier_relationship_months: 24,
        evidence_ref: 'Partnership deed verified',
      }))
    })

    // Test demonstration fixture selection
    const fixtureSelect = screen.getByRole('combobox', { name: 'Select demonstration fixture' })
    fireEvent.change(fixtureSelect, { target: { value: 'FICT-MATCH-001' } })

    await waitFor(() => {
      expect(koshApi.saveFinancingEvidence).toHaveBeenCalledWith(7, {
        apply_fixture: 'FICT-MATCH-001',
      })
    })

    cleanup()
    client.clear()
  })
})

