import {useEffect,useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {get,post} from '../api/client'
import {Card,ErrorBox,Status,PageHeader,Notice,Empty} from '../components/Common'

export default function Production(){
  const qc=useQueryClient()
  const cores=useQuery({queryKey:['cores'],queryFn:()=>get<any[]>('/core-types')})
  const reqs=useQuery({queryKey:['reqs'],queryFn:()=>get<any[]>('/production/requests'),refetchInterval:3000})
  const [core,setCore]=useState('CORE-A')
  const [qty,setQty]=useState(55)
  const [active,setActive]=useState<any>(null)
  const [plan,setPlan]=useState<any>(null)
  const [sim,setSim]=useState<any>(null)
  const [exec,setExec]=useState<any>(null)

  useEffect(()=>{if(cores.data?.length&&!cores.data.some(c=>c.code===core))setCore(cores.data[0].code)},[cores.data,core])

  const prepare=useMutation({
    mutationFn:async()=>{
      setPlan(null);setSim(null);setExec(null)
      const r=await post<any>('/production/requests',{core_type_code:core,requested_quantity:qty})
      setActive(r)
      const p=await post<any>(`/production/requests/${r.id}/plan`)
      setPlan(p)
      const s=await post<any>(`/production/requests/${r.id}/simulate`)
      setSim(s)
      return {r,p,s}
    },
    onSuccess:()=>qc.invalidateQueries()
  })
  const execute=useMutation({
    mutationFn:()=>post<any>(`/production/requests/${active.id}/execute`),
    onSuccess:r=>{setExec(r);qc.invalidateQueries()}
  })

  const passed=sim?.status==='PASS'
  const shortage=plan?.shortage?.shortage||0
  const planned=plan?.plan?.total_planned??0

  return <>
    <PageHeader
      title="Production"
      subtitle="Enter the need. The system chooses eligible boxes, validates FIFO and drying, simulates the route, then the robot executes autonomously."
      actions={<Link className="btn secondary" to="/digital-twin">Watch Live Warehouse</Link>}
    />

    <div className="productionV6">
      <Card className="productionOrderCard">
        <div className="productionHeroLabel">NEW ORDER</div>
        <h3>What does production need?</h3>
        <p>The operator never selects a box, rack, slot or robot path.</p>
        <div className="productionInputGrid">
          <label>Core type<select value={core} onChange={e=>setCore(e.target.value)}>{cores.data?.filter(c=>c.active).map(c=><option key={c.id} value={c.code}>{c.code} — {c.name}</option>)}</select></label>
          <label>Quantity<input type="number" min="1" value={qty} onChange={e=>setQty(Math.max(1,Number(e.target.value)||1))}/></label>
        </div>
        <div className="presetRow"><button className="preset" onClick={()=>setQty(20)}>20</button><button className="preset recommended" onClick={()=>{setCore('CORE-A');setQty(55)}}>55 · FIFO demo</button><button className="preset" onClick={()=>setQty(100)}>100</button></div>
        <button className="primaryWide orderPrimary" onClick={()=>prepare.mutate()} disabled={prepare.isPending}>{prepare.isPending?'System is deciding…':'Check availability & build plan'}</button>
        <ErrorBox error={prepare.error}/>
      </Card>

      <Card className="productionDecisionCard">
        {!active?<div className="decisionEmpty"><span>AI</span><b>Decision preview</b><p>The selected boxes, validation result and estimated movement will appear here.</p></div>:<>
          <div className="decisionTopLine"><div><small>ORDER</small><b>{core} × {qty}</b></div><Status value={sim?.status||'PLANNING'}/></div>
          <div className="decisionMetricRow">
            <div><small>Planned</small><b>{planned}/{qty}</b></div>
            <div><small>Boxes</small><b>{plan?.items?.length??0}</b></div>
            <div><small>Robot distance</small><b>{sim?.estimated_robot_distance_m?.toFixed?.(1)??'—'} m</b></div>
            <div><small>Estimated time</small><b>{sim?.estimated_duration_s?.toFixed?.(1)??'—'} s</b></div>
          </div>
          {shortage>0?<Notice tone="warning" title={`Shortage of ${shortage} pieces`}><span>The system refuses to consume protected drying stock. Next readiness is shown in the advanced details.</span></Notice>:sim&&<Notice tone="success" title="Plan validated"><span>FIFO, 24h drying, single-robot and safety rules passed. The robot may execute this order.</span></Notice>}
          <div className="productionBoxFlow">
            {plan?.items?.map((i:any)=><div key={i.id} className="flowBox"><span>#{i.fifo_rank}</span><div><b>{i.source_slot}</b><small>{i.return_required?'Partial box will be returned intelligently':'Box will be emptied'}</small></div><strong>−{i.quantity_to_take}</strong></div>)}
          </div>
          {sim&&<details className="advancedDecision"><summary>Show simulation details</summary><div className="advancedDecisionBody"><div><b>FIFO</b><span>{sim.fifo_validation?'PASS':'FAIL'}</span></div><div><b>24h drying</b><span>{sim.drying_validation?'PASS':'FAIL'}</span></div><div><b>Safety</b><span>{sim.safety_validation?'PASS':'FAIL'}</span></div><div><b>Partial returns</b><span>{sim.partial_boxes_returned??0}</span></div>{sim.return_decisions?.map((d:any)=><div key={d.box_code}><b>{d.box_code} return</b><span>{d.selected_slot}</span></div>)}</div></details>}
          <div className="approveRunBar">
            <div><small>{exec?'The order is live. The backend control loop now owns execution.':'One approval starts autonomous execution.'}</small></div>
            {exec?<Link className="btn" to="/digital-twin">Watch order live →</Link>:<button onClick={()=>execute.mutate()} disabled={!passed||execute.isPending}>{execute.isPending?'Starting…':'Approve & run'}</button>}
          </div>
          <ErrorBox error={execute.error}/>
        </>}
      </Card>
    </div>

    <Card title="RECENT ORDERS">
      {reqs.data?.length?<div className="responsiveTable"><table><thead><tr><th>Created</th><th>Quantity</th><th>Status</th><th></th></tr></thead><tbody>{reqs.data.slice(0,8).map(r=><tr key={r.id}><td>{new Date(r.created_at).toLocaleString()}</td><td><b>{r.requested_quantity}</b></td><td><Status value={r.status}/></td><td><Link to={`/production/${r.id}`}>Open →</Link></td></tr>)}</tbody></table></div>:<Empty text="No production orders yet."/>}
    </Card>
  </>
}
