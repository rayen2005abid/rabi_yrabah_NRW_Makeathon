import {useState} from 'react'
import {Link} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {Card,PageHeader,Notice,Status,ErrorBox} from '../components/Common'

type Scenario={id:string;title:string;subtitle:string;description:string;kind:string}

export default function DemoConsole(){
  const qc=useQueryClient()
  const scenarios=useQuery({queryKey:['scenarios'],queryFn:()=>get<Scenario[]>('/demo/scenarios')})
  const twin=useQuery({queryKey:['scenarioTwin'],queryFn:()=>get<any>('/digital-twin'),refetchInterval:350})
  const [last,setLast]=useState<any>(null)
  const run=useMutation({
    mutationFn:(id:string)=>post<any>(`/demo/scenarios/${id}/run`),
    onSuccess:r=>{setLast(r);qc.invalidateQueries()},
  })
  const activeId=last?.scenario_id
  const live=twin.data?.live_execution
  return <>
    <PageHeader title="Scenario Lab" subtitle="Start a complete warehouse situation with one click, then watch the same autonomous robot execute it live through racks, aisles and the transfer lane." actions={<Link className="btn secondary" to="/digital-twin">Open Live Simulation</Link>}/>

    <Notice tone="info" title="Every scenario is real application state"><span>Starting a scenario resets to the deterministic seed, creates real orders/packages, runs the real planning/simulation logic and queues the real robot tasks. AUTO mode then executes them.</span></Notice>

    <div className="scenarioGridV7">
      {(scenarios.data||[]).map(s=><Card key={s.id} className={`scenarioCardV7 ${activeId===s.id?'active':''}`}>
        <div className="scenarioTypeV7">{s.kind.replaceAll('_',' ')}</div>
        <h3>{s.title}</h3><b>{s.subtitle}</b><p>{s.description}</p>
        <button className="primaryWide" onClick={()=>run.mutate(s.id)} disabled={run.isPending}>{run.isPending&&run.variables===s.id?'Preparing scenario…':activeId===s.id?'Restart scenario':'Run scenario'}</button>
      </Card>)}
    </div>
    <ErrorBox error={run.error}/>

    {last&&<div className="scenarioResultV7">
      <Card>
        <div className="scenarioResultHeadV7"><div><small>ACTIVE SCENARIO</small><b>{scenarios.data?.find(s=>s.id===last.scenario_id)?.title||last.scenario_id}</b></div><Status value={last.status}/></div>
        <div className="scenarioObjectsV7">
          {(last.orders||[]).map((o:any)=><div key={o.id}><span>ORDER</span><b>{o.core_type} × {o.quantity}</b><small>{o.simulation?.status} · planned {o.plan?.total_planned}/{o.plan?.total_requested}</small></div>)}
          {(last.inbound_boxes||[]).map((b:any)=><div key={b.id}><span>NEW PACKAGE</span><b>{b.code}</b><small>{b.core_type} · {b.quantity} pcs</small></div>)}
        </div>
        {(last.notes||[]).map((n:string,i:number)=><p className="scenarioNoteV7" key={i}>{n}</p>)}
      </Card>
      <Card>
        <div className="scenarioResultHeadV7"><div><small>LIVE ROBOT</small><b>{live?.active?live.phase.replaceAll('_',' '):'Autonomous standby'}</b></div><Status value={twin.data?.robot?.mode||'IDLE'}/></div>
        <div className="liveScenarioProgressV7"><div><strong>{Math.round((live?.progress||0)*100)}%</strong><span>{live?.floor_label||'Transfer zone'}</span></div><div><i style={{width:`${(live?.progress||0)*100}%`}}/></div></div>
        <div className="scenarioQuickV7"><span><small>QUEUE</small><b>{twin.data?.task_queue?.length||0}</b></span><span><small>BOX</small><b>{twin.data?.decision?.box_code||'—'}</b></span><span><small>MODE</small><b>{twin.data?.autonomy?.mode||'AUTO'}</b></span></div>
        <Link className="btn fullBtn" to="/digital-twin">Watch robot movement now →</Link>
      </Card>
    </div>}
  </>
}
