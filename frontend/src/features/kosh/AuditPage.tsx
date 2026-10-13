import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { PageLoader } from '@/components/ui/LoadingSpinner'

export const AuditPage=()=>{const {activeSellerId}=useSeller();const [verification,setVerification]=useState('');const query=useQuery({queryKey:['kosh','audit',activeSellerId],queryFn:()=>koshApi.audit(activeSellerId!),enabled:activeSellerId!==null});if(query.isLoading)return <PageLoader/>;return <section aria-label="Audit"><div className="flex justify-between"><h2 className="text-xl font-semibold">Audit</h2><button className="rounded bg-blue-700 px-3 py-1 text-white" onClick={()=>koshApi.verifyAudit(activeSellerId!).then(r=>setVerification(r.valid?`VALID, ${r.entries} entries`:`BROKEN: ${r.reason}`))}>Verify chain</button></div>{verification&&<p role="status">{verification}</p>}<div className="mt-4 space-y-2">{query.data?.items.length?query.data.items.map(row=><div className="rounded border bg-white p-3" key={row.sequence}><span>#{row.sequence} {row.action}</span><span className="ml-2 text-gray-500">{row.actor_type} - {row.tier} - {row.policy_decision}</span></div>):<p>No audit entries yet.</p>}</div></section>}
