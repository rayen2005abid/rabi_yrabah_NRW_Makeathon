import {useEffect,useMemo,useState} from 'react'
import {Link} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {Card,ErrorBox,PageHeader,Status} from '../components/Common'

type Pt={x:number;y:number}
const iso=(x:number,y:number):Pt=>({x:50+(x-y)*42,y:10+(x+y)*34})
const pts=(list:Pt[])=>list.map(p=>`${p.x},${p.y}`).join(' ')

const scenarios=[
  {id:'new_package',n:'01',title:'New package',sub:'camera + weight → AI → smart slot → robot'},
  {id:'multiple_inbound',n:'02',title:'Package flow',sub:'3 packages enter one after another automatically'},
  {id:'single_fifo',n:'03',title:'Production 55',sub:'24h + FIFO → exact boxes → extraction'},
  {id:'multi_order_rush',n:'04',title:'Order rush',sub:'3 production orders → single-robot scheduling'},
  {id:'mixed_flow',n:'05',title:'Mixed traffic',sub:'inbound package + production at the same time'},
  {id:'partial_return',n:'06',title:'Partial return',sub:'pick + intelligent return-slot decision'},
  {id:'shortage',n:'07',title:'Shortage',sub:'drying rule blocks unsafe execution'},
]

export default function JuryShowcase(){
  const qc=useQueryClient()
  const [story,setStory]=useState<any>(null)
  const [selectedScenario,setSelectedScenario]=useState('new_package')
  const twin=useQuery({queryKey:['juryTwin'],queryFn:()=>get<any>('/digital-twin'),refetchInterval:90})
  const station=useQuery({queryKey:['juryStation'],queryFn:()=>get<any>('/capture/station'),refetchInterval:500})
  const scenarioState=useQuery({queryKey:['juryScenarioList'],queryFn:()=>get<any[]>('/demo/scenarios'),staleTime:60000})
  useEffect(()=>{post('/digital-twin/speed',{multiplier:10}).catch(()=>{})},[])
  const refresh=()=>qc.invalidateQueries()

  const demo=useMutation({mutationFn:async(kind:string)=>{
    setSelectedScenario(kind)
    await post('/demo/reset')
    await post('/digital-twin/speed',{multiplier:10})
    const result=await post<any>(`/demo/scenarios/${kind}/run`)
    return {kind,result}
  },onSuccess:r=>{setStory(r);refresh()}})

  const live=twin.data?.live_execution
  const decision=twin.data?.decision
  const robot=twin.data?.robot
  const route=(live?.journey_stage==='PREPARE'||live?.journey_stage==='PASSAGE_TO_SOURCE')?(live?.approach_route||[]):(live?.transfer_route||[])
  const routeIso=useMemo(()=>route.map((n:any)=>iso(n.x,n.y)),[route])
  const robotIso=iso(live?.floor_x??.08,live?.floor_y??.08)
  const progress=Math.round((live?.progress||0)*100)
  const decisionReasons=decision?.reasons||[]
  const activeMeta=(scenarioState.data||[]).find(s=>s.id===selectedScenario)
  const orders=story?.result?.orders||[]
  const inbound=story?.result?.inbound_boxes||[]
  const stage=(live?.journey_stage||'IDLE').replaceAll('_',' ')

  const rackShapes=[.18,.38,.58,.78].map((y,i)=>{
    const a=iso(.33,y-.045),b=iso(.92,y-.045),c=iso(.92,y+.045),d=iso(.33,y+.045)
    return {i:i+1,top:[a,b,c,d],front:[d,c,{x:c.x,y:c.y+4},{x:d.x,y:d.y+4}]}
  })
  const floor=pts([iso(.03,.03),iso(.97,.03),iso(.97,.97),iso(.03,.97)])

  return <>
    <PageHeader title="Demo Showcase" subtitle="A fast presentation mode: one click launches a real scenario, the robot follows the physical path, and the system explains every important decision." actions={<><span className="jurySpeedBadge">DEMO SPEED · 10×</span><Link className="btn secondary" to="/">Factory Console</Link><Link className="btn secondary" to="/digital-twin">Detailed Robot View</Link></>}/>

    <section className="juryPremiumHero">
      <div className="juryPremiumCopy"><small>SOPAL TEC · SMART CORE WAREHOUSE</small><h2>See it. Understand it. Watch it move.</h2><p>Automatic box intake, intelligent storage, FIFO production and passage-aware robot movement in one live story.</p></div>
      <div className="juryHeroTelemetry"><div><small>SYSTEM</small><b>{robot?.fault?'FAULT':'AUTONOMOUS'}</b></div><div><small>ROBOT</small><b>{robot?.mode||'OFFLINE'}</b></div><div><small>ACTIVE STAGE</small><b>{live?.active?stage:'READY'}</b></div><div><small>PROGRESS</small><b>{progress}%</b></div></div>
    </section>

    <div className="juryScenarioRail">
      {scenarios.map(s=><button key={s.id} className={selectedScenario===s.id?'active':''} onClick={()=>demo.mutate(s.id)} disabled={demo.isPending}><span>{s.n}</span><div><b>{s.title}</b><small>{s.sub}</small></div><em>→</em></button>)}
    </div>
    <ErrorBox error={demo.error}/>

    <div className="juryPremiumGrid">
      <Card className="juryIsoCard">
        <div className="juryPanelHead"><div><small>LIVE WAREHOUSE · PSEUDO 3D</small><b>{activeMeta?.title||'Choose a scenario'}</b></div><strong>{progress}%</strong></div>
        <div className="juryIsoScene">
          <svg viewBox="0 0 100 100" role="img" aria-label="Isometric warehouse movement simulation">
            <polygon points={floor} className="isoFloor"/>
            <polyline points={pts([iso(.18,.08),iso(.18,.88)])} className="isoTransferLane"/>
            <text x="17" y="83" className="isoSmallLabel">TRANSFER LANE</text>
            {rackShapes.map(r=><g key={r.i} className={decision?.chosen_target?.startsWith(`R${r.i}-`)||decision?.chosen_source?.startsWith(`R${r.i}-`)?'isoRack active':'isoRack'}>
              <polygon points={pts(r.top)} className="isoRackTop"/>
              <polygon points={pts(r.front)} className="isoRackFront"/>
              <text x={(r.top[0].x+r.top[2].x)/2-4} y={(r.top[0].y+r.top[2].y)/2} className="isoRackLabel">R{r.i}</text>
            </g>)}
            <polygon points={pts([iso(.035,.035),iso(.14,.035),iso(.14,.13),iso(.035,.13)])} className="isoEntry"/>
            <text x="46" y="14" className="isoEntryLabel">ENTRY</text>
            {routeIso.length>1&&<polyline points={pts(routeIso)} className="isoRoute"/>}
            {routeIso.map((p:any,i:number)=><circle key={i} cx={p.x} cy={p.y} r={i===0||i===routeIso.length-1?1.45:.75} className={i===0?'isoNode start':i===routeIso.length-1?'isoNode end':'isoNode'}/>) }
            <g className={`isoRobot ${robot?.carrying_box?'loaded':''}`} transform={`translate(${robotIso.x} ${robotIso.y})`}>
              <ellipse cx="0" cy="2.6" rx="4" ry="2" className="isoRobotShadow"/>
              <rect x="-3.2" y="-3" width="6.4" height="5.8" rx="1.2" className="isoRobotBody"/>
              <rect x="-1.4" y="-8.5" width="2.8" height="6" rx=".8" className="isoRobotMast"/>
              <line x1="1.5" y1="-2.8" x2="6" y2="-2.8" className="isoRobotFork"/>
              {robot?.carrying_box&&<rect x="5.1" y="-5" width="4.8" height="4.8" rx=".7" className="isoRobotBox"/>}
              <text x="-1.8" y=".4" className="isoRobotText">R</text>
            </g>
          </svg>
          <div className="juryIsoCaption"><div><small>NOW</small><b>{live?.floor_label||'Autonomous standby'}</b></div><div><small>PATH</small><b>{live?.source_code||decision?.chosen_source||'HOME'} → {live?.target_code||decision?.chosen_target||'WAITING'}</b></div><div><small>STAGE</small><b>{live?.active?stage:'IDLE'}</b></div></div>
        </div>

        <div className="juryStoryTrack">
          {['Detect','Decide','Plan path','Move','Handle','Verify'].map((x,i)=>{const done=progress>=(i+1)*16;const current=progress>=i*16&&progress<(i+1)*16;return <div key={x} className={`${done?'done':''} ${current?'current':''}`}><span>{done?'✓':i+1}</span><b>{x}</b></div>})}
        </div>
      </Card>

      <div className="juryPremiumSide">
        <Card className="juryBrainCardV10">
          <div className="juryPanelHead"><div><small>WAREHOUSE BRAIN</small><b>Why this move?</b></div><Status value={decision?.status||'READY'}/></div>
          {decision?<><div className="juryDecisionHeroV10"><small>CHOSEN ACTION</small><b>{decision.chosen_source||'HOME'} → {decision.chosen_target||'HOME'}</b><span>{decision.task_type?.replaceAll('_',' ')}</span></div><div className="juryReasonStackV10">{decisionReasons.slice(0,4).map((r:any,i:number)=><div key={i}><span>{r.weight}</span><div><b>{r.label}</b><small>{r.value}</small></div></div>)}</div></>:<div className="juryEmptyBrain">Launch a scenario to show the selected box, route and destination logic.</div>}
        </Card>

        <Card className="juryScenarioStateV10">
          <div className="juryPanelHead"><div><small>SCENARIO STATE</small><b>{activeMeta?.subtitle||'No scenario active'}</b></div></div>
          <div className="juryScenarioFactsV10"><div><small>Orders</small><b>{orders.length}</b></div><div><small>Inbound boxes</small><b>{inbound.length}</b></div><div><small>Robot queue</small><b>{twin.data?.task_queue?.length||0}</b></div><div><small>Scale</small><b>{Number(station.data?.weight_kg||0).toFixed(2)} kg</b></div></div>
          {story?.result?.notes?.[0]&&<p className="juryScenarioNoteV10">{story.result.notes[0]}</p>}
        </Card>
      </div>
    </div>

    <div className="juryBottomGridV10">
      <Card title="WHAT THE VIEWER IS SEEING">
        <div className="juryProofRibbonV10"><div><span>1</span><b>Automatic inbound</b><small>image + weight</small></div><div><span>2</span><b>AI classification</b><small>core type</small></div><div><span>3</span><b>Quantity estimate</b><small>weight calibration</small></div><div><span>4</span><b>Intelligent slot</b><small>ranked decision</small></div><div><span>5</span><b>Path planning</b><small>passage aware</small></div><div><span>6</span><b>Robot action</b><small>rack + transfer lane</small></div></div>
      </Card>
      <Card title="LIVE CONFIDENCE">
        <div className="juryConfidenceV10"><div><small>Decision confidence</small><b>{decision?`${Math.round((decision.confidence||0)*100)}%`:'—'}</b></div><div><small>Current box</small><b>{decision?.box_code||'—'}</b></div><div><small>Route algorithm</small><b>{decision?.route?.algorithm||'A*'}</b></div></div>
      </Card>
    </div>
  </>
}
