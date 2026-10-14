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
    processDocument: vi.fn(),uploadDocument:vi.fn(),createConsent:vi.fn(),revokeConsent:vi.fn(),patchInvoice:vi.fn(),obligations:vi.fn().mockResolvedValue([]),
  },
}))

import { router } from '@/app/router'
import { koshApi } from '@/lib/api/kosh'

describe('Kosh protected routes', () => {
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
    }
    if(path==='/audit'){
      expect(screen.getByRole('button',{name:'Export JSONL'})).toBeInTheDocument()
      expect(await screen.findByText('injection detections: 1')).toBeInTheDocument()
    }
    cleanup();client.clear()
  })
})
