import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { PageLoader } from '@/components/ui/LoadingSpinner'
import { SandboxBanner } from '@/components/ui/SandboxBanner'
import { formatEnumLabel } from '@/lib/koshLabels'

export const ApprovalsPage=()=>{
  const {activeSellerId}=useSeller();const qc=useQueryClient()
  const [now,setNow]=useState(Date.now());const [message,setMessage]=useState('');const [busy,setBusy]=useState(false)
  const [codes,setCodes]=useState<Record<string,string>>({})
  const [tokens,setTokens]=useState<Record<string,{approval_token:string;expires_at:string}>>({})
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[])
  useEffect(()=>{setTokens({});setCodes({});setMessage('')},[activeSellerId])
  const enabled=activeSellerId!==null
  const intents=useQuery({queryKey:['kosh','intents',activeSellerId],queryFn:()=>koshApi.actionInbox(activeSellerId!),enabled})
  const plan=useQuery({queryKey:['kosh','plan',activeSellerId],queryFn:()=>koshApi.latestPlan(activeSellerId!),enabled,retry:false})
  const policy=useQuery({queryKey:['kosh','policy',activeSellerId],queryFn:()=>koshApi.policy(activeSellerId!),enabled})
  const canApprove=['OWNER','APPROVER'].includes(intents.data?.role??'')
  const inbox=useQuery({queryKey:['kosh','sandbox-inbox',activeSellerId],queryFn:()=>koshApi.sandboxInbox(activeSellerId!),enabled:enabled&&canApprove,retry:false})
  const outbox=useQuery({queryKey:['kosh','sandbox-outbox',activeSellerId],queryFn:()=>koshApi.sandboxOutbox(activeSellerId!),enabled})
  const timeline=useQuery({queryKey:['kosh','executions',activeSellerId],queryFn:()=>koshApi.executions(activeSellerId!),enabled})
  const run=async(task:()=>Promise<unknown>)=>{setBusy(true);setMessage('');try{await task();setMessage('Saved.');await qc.invalidateQueries({queryKey:['kosh']})}catch(error){const e=error as {response?:{data?:{detail?:unknown}};message?:string};setMessage(JSON.stringify(e.response?.data?.detail??e.message??'Request failed'))}finally{setBusy(false)}}
  const countdown=(expiry:string|null|undefined)=>expiry?`${Math.max(0,Math.ceil((Date.parse(expiry)-now)/1000))} seconds remaining`:'No approval token issued'
  return <section aria-label="Approvals" className="space-y-4">
    <SandboxBanner />
    <h2 className="text-xl font-semibold">Approvals</h2>
    <p>Review exact server-derived parameters. Execution uses the local sandbox only.</p>
    {message&&<p role="status">{message}</p>}{(intents.isError||policy.isError)&&<p role="alert">Unable to load approvals or policy.</p>}
    {policy.data?.role==='OWNER'&&<button className="rounded border px-3 py-1 bg-white hover:bg-gray-50" disabled={busy} onClick={()=>{const on=!policy.data?.seller_kill;if(window.confirm(`${on?'Enable':'Disable'} the seller kill switch? This changes whether actions can be approved and executed.`))void run(()=>koshApi.killSwitch(activeSellerId!,on))}}>{policy.data.seller_kill?'Disable':'Enable'} seller kill switch</button>}
    {policy.data?.global_kill&&<p role="alert">Global kill switch is enabled.</p>}
    {canApprove&&plan.data?.status==='VALID'&&<div><h3 className="font-semibold text-base mb-2">Create an intent from the current valid plan</h3><div className="flex flex-wrap gap-2">{plan.data.lines.map(line=><button className="rounded border px-3 py-1 bg-white hover:bg-gray-50 text-sm" key={line.id} disabled={busy} onClick={()=>void run(()=>koshApi.proposeIntent(activeSellerId!,line.id))}>Propose {line.product_id} (Line {line.id})</button>)}</div></div>}
    <h3 className="font-semibold text-base mt-4">Intent inbox</h3>{!intents.data?.items.length&&<div className="rounded border bg-gray-50 p-4 text-center text-sm text-gray-600"><p>No action intents.</p><p className="text-xs text-gray-500 mt-1">Generate a plan on the Plan page to propose financing or reminder actions.</p></div>}
    {intents.data?.items.map(intent=>{const token=tokens[intent.id];return <article key={intent.id} className="rounded border p-3 space-y-2">
      <div className="flex items-center gap-2">
        <h4 className="font-semibold">{intent.action_type}</h4>
        <span className="px-2 py-0.5 rounded text-xs font-bold bg-blue-100 text-blue-800">{intent.tier}</span>
        <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800" title={intent.status}>{formatEnumLabel(intent.status)}</span>
      </div>{intent.plan_line_id?<Link to={`/plan#plan-line-${intent.plan_line_id}`} className="text-blue-600 underline text-sm">Plan line {intent.plan_line_id}</Link>:<Link to="/operations/collections" className="text-blue-600 underline text-sm">Native module evidence</Link>}
      <h5>Exact parameters</h5><pre className="whitespace-pre-wrap">{JSON.stringify(intent.params,null,2)}</pre>
      <h5>Policy reasons</h5><pre className="whitespace-pre-wrap">{JSON.stringify(intent.policy_decision,null,2)}</pre><p>{countdown(token?.expires_at??intent.expires_at)}</p>
      {canApprove&&['BLOCKED','EXPIRED','FAILED'].includes(intent.status)&&<button disabled={busy} onClick={()=>void run(()=>koshApi.recheckIntent(activeSellerId!,intent.id))}>Recheck current policy {intent.id}</button>}
      {canApprove&&['PROPOSED','PENDING_APPROVAL'].includes(intent.status)&&<>
        {intent.tier==='T3'&&<><button disabled={busy} onClick={()=>void run(()=>koshApi.requestOtp(activeSellerId!,intent.id))}>Request OTP</button><label>OTP for {intent.id}<input aria-label={`OTP for ${intent.id}`} inputMode="numeric" maxLength={6} value={codes[intent.id]??''} onChange={e=>setCodes({...codes,[intent.id]:e.target.value})}/></label></>}
        <button disabled={busy||(intent.tier==='T3'&&!/^\d{6}$/.test(codes[intent.id]??''))} onClick={()=>void run(async()=>{const value=await koshApi.approveIntent(activeSellerId!,intent.id,codes[intent.id]);setTokens({...tokens,[intent.id]:value});setCodes({...codes,[intent.id]:''})})}>Approve {intent.id}</button>
        <button disabled={busy} onClick={()=>void run(()=>koshApi.rejectIntent(activeSellerId!,intent.id))}>Reject {intent.id}</button>
      </>}
      {canApprove&&intent.status==='APPROVED'&&<button disabled={busy} onClick={()=>void run(()=>koshApi.rejectIntent(activeSellerId!,intent.id))}>Reject approved intent {intent.id}</button>}
      {canApprove&&intent.status==='APPROVED'&&token&&<button disabled={busy||Date.parse(token.expires_at)<=now} onClick={()=>void run(async()=>{await koshApi.executeIntent(activeSellerId!,intent.id,token.approval_token);setTokens(current=>{const next={...current};delete next[intent.id];return next})})}>Execute in sandbox {intent.id}</button>}
    </article>})}
    <h3>Sandbox inbox · private OTP deliveries</h3>{inbox.isError&&<p>Private OTP inbox unavailable in this environment.</p>}{inbox.data?.items.map(item=><pre className="whitespace-pre-wrap" key={item.id}>{JSON.stringify(item,null,2)}</pre>)}
    <h3>Sandbox messages · no external delivery</h3>{outbox.data?.items.map(item=><pre className="whitespace-pre-wrap" key={item.id}>{JSON.stringify(item,null,2)}</pre>)}
    <h3>Executions timeline · before and after forecast</h3>{timeline.data?.items.map(item=><pre className="whitespace-pre-wrap" key={item.id}>{JSON.stringify(item,null,2)}</pre>)}
    {canApprove&&<button disabled={busy} onClick={()=>void run(()=>koshApi.blockedDocumentPayment(activeSellerId!))}>Test blocked document payment</button>}
  </section>
}
