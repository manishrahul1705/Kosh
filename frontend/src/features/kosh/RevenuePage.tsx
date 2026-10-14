import {useQuery} from '@tanstack/react-query'
import {useSeller} from '@/app/SellerContext'
import {koshApi} from '@/lib/api/kosh'
import {formatPaiseINR} from '@/lib/formatMoney'
import {Link} from 'react-router-dom'
export const RevenuePage=()=>{const {activeSellerId}=useSeller();const query=useQuery({queryKey:['kosh','revenue',activeSellerId],queryFn:()=>koshApi.revenueSignal(activeSellerId!),enabled:activeSellerId!==null});return <section aria-label="Revenue signal"><h2>Optional revenue signal</h2><p>{query.data?.model}</p><p>{query.data?.reason}</p><p>{query.data?.explainability}</p><p>{query.data?.cash_timing}</p><p>Source: {query.data?.source}. Enable or disable this separately labelled input on <Link to="/cash">Cash</Link>. Monte Carlo remains the authoritative cash forecast.</p><table><thead><tr><th>Issue week</th><th>Revenue signal</th><th>Level contribution</th><th>Trend contribution</th></tr></thead><tbody>{query.data?.weeks.map(w=><tr key={w.week_index}><td>{w.week_index}</td><td>{formatPaiseINR(w.predicted_revenue_paise)}</td><td>{formatPaiseINR(w.level_contribution_paise)}</td><td>{formatPaiseINR(w.trend_contribution_paise)}</td></tr>)}</tbody></table></section>}
