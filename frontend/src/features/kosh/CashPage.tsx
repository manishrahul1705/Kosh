import { useState } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { Area,AreaChart,CartesianGrid,Legend,Line,ResponsiveContainer,Tooltip,XAxis,YAxis } from 'recharts'
import { useSeller } from '@/app/SellerContext'
import { ErrorAlert } from '@/components/ui/ErrorAlert'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { koshApi,Forecast } from '@/lib/api/kosh'
import { formatPaiseINR } from '@/lib/formatMoney'

const lakh=(value:number)=>`${(value/10_000_000).toFixed(1)}L`

export const CashPage=()=>{
  const {activeSellerId}=useSeller();const qc=useQueryClient();const [showForecast,setShowForecast]=useState(true);const [drawer,setDrawer]=useState(false);const [shift,setShift]=useState(0);const [scenario,setScenario]=useState<Forecast|null>(null)
  useQuery({queryKey:['kosh','ledger',activeSellerId],queryFn:()=>koshApi.ledger(activeSellerId!),enabled:activeSellerId!==null})
  const forecast=useQuery({queryKey:['kosh','forecast',activeSellerId],queryFn:()=>koshApi.forecast(activeSellerId!),enabled:activeSellerId!==null,retry:false})
  const analysis=useQuery({queryKey:['kosh','analysis',activeSellerId],queryFn:()=>koshApi.analysis(activeSellerId!),enabled:activeSellerId!==null})
  const backtest=useQuery({queryKey:['kosh','backtest',activeSellerId],queryFn:()=>koshApi.backtest(activeSellerId!),enabled:activeSellerId!==null,retry:false})
  const run=useMutation({mutationFn:()=>koshApi.runForecast(activeSellerId!),onSuccess:()=>qc.invalidateQueries({queryKey:['kosh','forecast',activeSellerId]})})
  if(forecast.isLoading)return <PageLoader/>;if(forecast.isError)return <section><h2 className="text-xl font-semibold">Cash</h2><ErrorAlert message="No forecast is available."/><button className="rounded bg-blue-700 px-3 py-2 text-white" onClick={()=>run.mutate()}>Run forecast</button></section>
  const data=scenario??forecast.data;if(!data)return <p>Select a seller.</p>;const alert=data.alert;const chart=data.weeks.map(row=>({...row,label:`W${row.week_index}`,low:row.p10_closing_balance_paise,range:row.p90_closing_balance_paise-row.p10_closing_balance_paise,buffer:data.run.buffer_paise,forecast:showForecast?row.expected_inflow_forecast_paise:0}))
  const coverage=(backtest.data?.coverage_by_horizon??{}) as Record<string,number>;const metrics=analysis.data??{}
  return <section aria-label="Cash forecast" className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-xl font-semibold">13-week cash forecast</h2><div><label className="mr-3"><input type="checkbox" checked={showForecast} onChange={event=>setShowForecast(event.target.checked)}/> Include forecast sales</label><button className="rounded border px-3 py-1" onClick={()=>setDrawer(!drawer)}>What-if</button></div></div>
    {alert&&<div role="alert" className="rounded border-l-4 border-amber-500 bg-amber-50 p-4"><strong>{alert.summary??`Week ${alert.week_index}: ${(alert.probability*100).toFixed(0)}% chance below buffer`}</strong><p>Expected shortfall {formatPaiseINR(alert.expected_shortfall_paise)}</p><ol className="list-decimal pl-5">{alert.causes.map((cause,index)=><li key={index}>{cause.customer??cause.type}: {formatPaiseINR(cause.amount_paise)} ({formatPaiseINR(cause.contribution_paise)} contribution)</li>)}</ol>{alert.id&&<button className="underline" onClick={()=>koshApi.acknowledgeAlert(activeSellerId!,alert.id!)}>Acknowledge</button>}</div>}
    {data.under_review_paise>0&&<a href="/ledger" className="block rounded bg-amber-50 p-3 underline">Under review: {formatPaiseINR(data.under_review_paise)} excluded</a>}
    <div className="h-80 rounded border bg-white p-3"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chart}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="label"/><YAxis tickFormatter={lakh}/><Tooltip formatter={(value)=>formatPaiseINR(Number(value))}/><Legend/><Area dataKey="low" stackId="band" stroke="none" fill="transparent"/><Area name="P10-P90" dataKey="range" stackId="band" stroke="#93c5fd" fill="#dbeafe"/><Line name="P50" dataKey="p50_closing_balance_paise" stroke="#1d4ed8" strokeWidth={2}/><Line name="Buffer" dataKey="buffer" stroke="#dc2626" strokeDasharray="5 5"/></AreaChart></ResponsiveContainer></div>
    {drawer&&<div className="rounded border bg-white p-4"><h3 className="font-semibold">What-if scenario</h3><label>Customer delay shift <input aria-label="Customer delay shift" type="range" min={-30} max={30} value={shift} onChange={event=>setShift(Number(event.target.value))}/> {shift} days</label><button className="ml-3 rounded bg-blue-700 px-3 py-1 text-white" onClick={()=>koshApi.whatIf(activeSellerId!,{customer_delay_shift_days:Object.fromEntries((alert?.causes??[]).filter(c=>c.counterparty_id).map(c=>[c.counterparty_id,shift])),exclude_counterparties:[],extra_inflows:[]}).then(setScenario)}>Apply</button></div>}
    <div className="grid gap-3 md:grid-cols-2"><div className="rounded border bg-white p-4"><h3 className="font-semibold">Back-test</h3>{Object.keys(coverage).length?<p>P10-P90 coverage: {Object.entries(coverage).map(([key,value])=>`H${key} ${(value*100).toFixed(0)}%`).join(', ')}</p>:<p>No back-test yet.</p>}</div><div className="rounded border bg-white p-4"><h3 className="font-semibold">Business analysis</h3><p>DSO {String(metrics.dso_days??'-')} days - DPO {String(metrics.dpo_days??'-')} days - CCC {String(metrics.cash_conversion_cycle_days??'-')} days</p><p>Top 3 customer share {metrics.top_3_customer_share==null?'-':`${(Number(metrics.top_3_customer_share)*100).toFixed(0)}%`}</p></div></div>
  </section>
}
