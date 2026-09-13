import {useMemo,useState} from 'react'
import {Link} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {Card,Status,PageHeader,Notice,Empty} from '../components/Common'

type TwinBox={id:string;code:string;core_type:string;quantity:number;initial_quantity:number;status:string}
type TwinSlot={id:string;code:string;type:string;status:string;rack_face:number|null;column:number|null;level:number|null;x:number;y:number;z:number;box?:TwinBox|null}
type RouteNode={node_id:string;x:number;y:number;label:string;kind:string}
type Decision={
  task_id:string;request_id:string|null;task_type:string;decision_type:string;chosen_source:string|null;chosen_target:string|null;
  box_code:string|null;confidence:number;reasons:{label:string;value:string;weight:number}[];candidates:any[];
  approach_route:{nodes:RouteNode[]};route:{nodes:RouteNode[];algorithm:string;distance_units:number};status:string
}
type LiveExecution={
  active:boolean;task_id:string|null;phase:string;phase_progress:number;progress:number;remaining_s:number;source_code:string|null;target_code:string|null;
  playback_speed:number;floor_x:number;floor_y:number;floor_label:string;journey_stage:string;route_progress:number;approach_route:RouteNode[];transfer_route:RouteNode[];
  source_is_storage:boolean;target_is_storage:boolean
}
type TwinState={
  autonomy:{mode:string};
  robot:{x:number;y:number;z:number;mode:string;carrying_box:boolean;current_task_id:string|null;fault:string|null;estop:boolean};
  live_execution:LiveExecution;
  slots:TwinSlot[];task_queue:any[];decision:Decision|null;
  picking_station:{state:string;slot:TwinSlot|null;pick_context?:{suggested_quantity:number|null;request_id:string|null;fifo_rank:number|null}|null}
}

const range=(n:number)=>Array.from({length:n},(_,i)=>i+1)
const pct=(n:number)=>Math.round(Math.max(0,Math.min(1,n))*100)
const slotClass=(s:TwinSlot)=>`${s.status.toLowerCase()} ${s.box?.status?.toLowerCase()||''}`

const testScenarios=[
  {id:'capture_auto',n:'01',title:'Automatic entry',sub:'camera + weight → AI → smart slot → robot'},
  {id:'single_fifo',n:'02',title:'Production 55',sub:'FIFO order with partial return'},
  {id:'multi_order_rush',n:'03',title:'Multiple orders',sub:'3 orders through one robot'},
  {id:'multiple_inbound',n:'04',title:'3 incoming boxes',sub:'sequential ENTRY handling'},
  {id:'mixed_flow',n:'05',title:'Mixed traffic',sub:'inbound + production together'},
  {id:'partial_return',n:'06',title:'Smart return',sub:'partial pick → intelligent slot'},
  {id:'shortage',n:'07',title:'Shortage',sub:'24h rule blocks unsafe stock'},
]

const macroStages=[
  ['PREPARE','Safety'],['PASSAGE_TO_SOURCE','Go to source'],['SOURCE_WORK','Source handling'],['PASSAGE','Exit source'],['TRANSFER_LANE','Transfer lane'],['TARGET_WORK','Target handling'],['VERIFY','Verify']
]

export default function DigitalTwin(){
  const qc=useQueryClient()
  const [selected,setSelected]=useState<TwinSlot|null>(null)
  const [selectedScenario,setSelectedScenario]=useState('capture_auto')
  const [testResult,setTestResult]=useState<any>(null)
  const twin=useQuery({queryKey:['twin'],queryFn:()=>get<TwinState>('/digital-twin'),refetchInterval:90})
  const scenarioCatalog=useQuery({queryKey:['robotPathScenarioCatalog'],queryFn:()=>get<any[]>('/demo/scenarios'),staleTime:60000})
  const refreshAll=()=>{qc.invalidateQueries();}
  const launchTest=useMutation({mutationFn:async(id:string)=>{
    setSelectedScenario(id)
    await post('/demo/reset')
    await post('/digital-twin/speed',{multiplier:10})
    if(id==='capture_auto'){
      const capture=await post<any>('/capture/demo-arrival',{core_type:'CORE-D',quantity:24})
      return {scenario_id:id,status:'READY',inbound_boxes:[capture.box],capture,notes:['Automatic capture demo: image/type is simulated, quantity comes from the calibrated weight profile, then the real intake and robot task are used.']}
    }
    return await post<any>(`/demo/scenarios/${id}/run`)
  },onSuccess:r=>{setTestResult(r);refreshAll()}})
  const resetTest=useMutation({mutationFn:async()=>{const r=await post<any>('/demo/reset');await post('/digital-twin/speed',{multiplier:10});return r},onSuccess:r=>{setTestResult(null);refreshAll()}})
  const setSpeed=useMutation({mutationFn:(multiplier:number)=>post('/digital-twin/speed',{multiplier}),onSuccess:refreshAll})
  const data=twin.data
  const slots=data?.slots||[]
  const storage=useMemo(()=>slots.filter(s=>s.type==='STORAGE'),[slots])
  const specials=useMemo(()=>slots.filter(s=>s.type!=='STORAGE'),[slots])
  const decision=data?.decision
  const live=data?.live_execution
  const robot=data?.robot
  const sourceSlot=slots.find(s=>s.code===(live?.source_code||decision?.chosen_source))
  const targetSlot=slots.find(s=>s.code===(live?.target_code||decision?.chosen_target))
  const sourceRack=sourceSlot?.rack_face||null
  const targetRack=targetSlot?.rack_face||null
  const rawStage=live?.journey_stage||'IDLE'
  const stage=rawStage==='SOURCE_RACK'||rawStage==='SOURCE_STATION'?'SOURCE_WORK':rawStage==='TARGET_RACK'||rawStage==='TARGET_STATION'?'TARGET_WORK':rawStage
  const activeRack=(rawStage==='TARGET_RACK'?targetRack:rawStage==='SOURCE_RACK'?sourceRack:(targetRack||sourceRack||1))||1
  const rackSlots=storage.filter(s=>s.rack_face===activeRack)
  const maxCols=Math.max(1,...storage.map(s=>s.column||1))
  const maxLevels=Math.max(1,...storage.map(s=>s.level||1))
  const rackLookup=new Map(rackSlots.map(s=>[`${s.column}-${s.level}`,s]))
  const columns=range(maxCols)
  const levels=range(maxLevels).reverse()
  const maxRackX=Math.max(0.01,...rackSlots.map(s=>s.x))
  const maxRackZ=Math.max(0.01,...rackSlots.map(s=>s.z))
  const liftX=Math.max(2,Math.min(98,((robot?.x||0)/maxRackX)*100))
  const liftY=Math.max(2,Math.min(98,(1-((robot?.z||0)/maxRackZ))*100))
  const progress=pct(live?.progress||0)
  const blocked=!!robot?.fault||!!robot?.estop
  const activeFloorRoute=(rawStage==='PREPARE'||rawStage==='PASSAGE_TO_SOURCE')?(live?.approach_route||[]):(live?.transfer_route||[])
  const execution=useQuery({
    queryKey:['requestExecution',decision?.request_id],
    queryFn:()=>get<any>(`/production/requests/${decision!.request_id}/execution`),
    enabled:!!decision?.request_id,
    refetchInterval:500,
  })
  const routePolyline=activeFloorRoute.map(n=>`${n.x*100},${n.y*100}`).join(' ')
  const floorX=(live?.floor_x??0.08)*100
  const floorY=(live?.floor_y??0.08)*100
  const rackPhase=rawStage==='SOURCE_RACK'||rawStage==='TARGET_RACK'
  const loadPhase=live?.phase==='LOAD_BOX'
  const unloadPhase=live?.phase==='UNLOAD_BOX'
  const sourceBox=sourceSlot?.box||null
  const handledBox=sourceBox||targetSlot?.box||null
  const rackActionSlot=loadPhase?sourceSlot:unloadPhase?targetSlot:null
  const rackActionLeft=rackActionSlot?.column?((rackActionSlot.column-.5)/maxCols)*100:liftX
  const rackActionTop=rackActionSlot?.level?((maxLevels-rackActionSlot.level+.5)/maxLevels)*100:liftY
  const transferP=live?.phase_progress??0
  const movingBoxLeft=loadPhase?rackActionLeft+(liftX-rackActionLeft)*transferP:liftX+(rackActionLeft-liftX)*transferP
  const movingBoxTop=loadPhase?rackActionTop+(liftY-rackActionTop)*transferP:liftY+(rackActionTop-liftY)*transferP
  const nearestRouteIndex=activeFloorRoute.length?activeFloorRoute.reduce((best,n,i)=>{
    const d=Math.hypot(floorX-n.x*100,floorY-n.y*100)
    return d<best[1]?([i,d] as [number,number]):best
  },[0,Number.POSITIVE_INFINITY] as [number,number])[0]:0
  const currentNode=activeFloorRoute[nearestRouteIndex]||null
  const nextNode=activeFloorRoute[Math.min(nearestRouteIndex+1,Math.max(0,activeFloorRoute.length-1))]||null
  const robotAngle=nextNode?Math.atan2(nextNode.y*100-floorY,nextNode.x*100-floorX)*180/Math.PI:0

  return <>
    <PageHeader title="Live Robot Path" subtitle="See the robot follow the real route: rack → passage → transfer lane → target. The floor view shows the path and the rack view shows lift + fork movement inside the rack." actions={<><Link className="btn secondary" to="/">Factory Console</Link><Link className="btn secondary" to="/admin">Admin Panel</Link></>}/>

    <div className="simTopStripV7">
      <div className={blocked?'dangerState':'autoState'}><small>CONTROL</small><b>{blocked?'BLOCKED':data?.autonomy?.mode||'AUTO'}</b></div>
      <div><small>ROBOT</small><b>{robot?.mode||'OFFLINE'}</b></div>
      <div><small>ORDER</small><b>{decision?.request_id?.slice(0,8)||'Inbound / manual'}</b></div>
      <div><small>BOX</small><b>{decision?.box_code||'—'}</b></div>
      <div><small>PROGRESS</small><b>{progress}%</b></div>
    </div>

    {blocked?<Notice tone="danger" title="Robot stopped"><span>{robot?.fault||'Emergency stop active'}. Use the Admin Panel for recovery.</span></Notice>:<Notice tone="info" title={live?.active?live.phase.replaceAll('_',' '):'Autonomous standby'}><span>{live?.active?(live.floor_label||'Robot moving through the warehouse'):'Choose a test below. The scenario starts here and the robot moves in this same screen automatically.'}</span></Notice>}

    <Card className="robotTestBenchV11">
      <div className="robotTestBenchHeadV11">
        <div><small>TEST BENCH</small><b>Launch a scenario without leaving the Robot Path screen</b><span>Each button resets the demo to a known state, launches the real backend workflow, and keeps the animation on this page.</span></div>
        <div className="robotTestBenchActionsV11"><button className="secondary" onClick={()=>resetTest.mutate()} disabled={resetTest.isPending}>Reset</button><div className="speedSwitchV11"><button onClick={()=>setSpeed.mutate(4)}>4×</button><button className={(live?.playback_speed||10)===10?'active':''} onClick={()=>setSpeed.mutate(10)}>10×</button><button onClick={()=>setSpeed.mutate(15)}>15×</button></div></div>
      </div>
      <div className="robotScenarioGridV11">
        {testScenarios.map(s=><button key={s.id} className={selectedScenario===s.id?'active':''} onClick={()=>launchTest.mutate(s.id)} disabled={launchTest.isPending}>
          <span>{s.n}</span><div><b>{s.title}</b><small>{s.sub}</small></div><em>{launchTest.isPending&&selectedScenario===s.id?'…':'▶'}</em>
        </button>)}
      </div>
      {testResult&&<div className="robotTestResultV11"><div><small>ACTIVE TEST</small><b>{testScenarios.find(s=>s.id===selectedScenario)?.title}</b></div><div><small>STATUS</small><b>{testResult.status||'READY'}</b></div><div><small>ORDERS</small><b>{testResult.orders?.length||0}</b></div><div><small>INBOUND</small><b>{testResult.inbound_boxes?.length||0}</b></div><div className="robotTestNoteV11"><small>WHAT TO WATCH</small><b>{testResult.notes?.[0]||scenarioCatalog.data?.find(s=>s.id===selectedScenario)?.description||'Watch the robot follow the highlighted route below.'}</b></div></div>}
    </Card>

    <div className="journeyStepsV7">
      {macroStages.map(([key,label])=>{
        const current=stage===key
        const currentIndex=macroStages.findIndex(x=>x[0]===stage)
        const index=macroStages.findIndex(x=>x[0]===key)
        return <div key={key} className={`${current?'current':''} ${currentIndex>index?'done':''}`}><span>{currentIndex>index?'✓':index+1}</span><b>{label}</b></div>
      })}
    </div>

    <div className="simWorldGridV7">
      <Card className="floorMapCardV7">
        <div className="panelHeaderV7"><div><small>TOP-DOWN FLOOR</small><b>Passage & transfer-lane movement</b></div><span>{decision?.route?.algorithm||'A*'} path</span></div>
        <div className="floorMapV7">
          <svg viewBox="0 0 100 100" role="img" aria-label="Top-down warehouse floor simulation">
            <rect x="1" y="1" width="98" height="98" rx="3" className="floorBoundaryV7"/>
            <rect x="3" y="3" width="12" height="12" rx="2" className="transferZoneV7"/>
            <text x="4.2" y="7.4" className="floorLabelV7">AUTO</text><text x="4.2" y="10.1" className="floorLabelV7">ENTRY</text><text x="4.2" y="13" className="floorLabelV7">PICKING</text>
            <line x1="18" y1="8" x2="18" y2="88" className="transferSpineV7"/>
            <text x="12.5" y="95" className="axisLabelV7">TRANSFER LANE</text>
            {[18,38,58,78].map((y,i)=><g key={y}>
              <line x1="18" y1={y} x2="94" y2={y} className="rackAisleV7"/>
              <rect x="31" y={y-5.5} width="61" height="8" rx="1.8" className={activeRack===i+1?'rackBlockV7 active':'rackBlockV7'}/>
              <text x="34" y={y-.7} className="rackLabelV7">RACK {i+1} · 8×8</text>
              <text x="21" y={y-1.4} className="aisleLabelV7">AISLE {i+1}</text>
            </g>)}
            {routePolyline&&<polyline points={routePolyline} className="plannedRouteV7"/>}
            {(activeFloorRoute||[]).map((n,i)=><g key={`${n.node_id}-${i}`}><circle cx={n.x*100} cy={n.y*100} r={i===0||i===activeFloorRoute.length-1?1.8:1.1} className={i===0?'routeNodeStartV7':i===activeFloorRoute.length-1?'routeNodeEndV7':'routeNodeV7'}/></g>)}
            <g className={`robotFloorV7 robotForkliftV10 ${robot?.carrying_box?'loaded':''}`} transform={`translate(${floorX} ${floorY}) rotate(${robotAngle})`}>
              <rect x="-3.4" y="-2.7" width="6.8" height="5.4" rx="1.1" className="robotFloorBodyV10"/>
              <circle cx="-2.3" cy="3.1" r=".9" className="robotFloorWheelV10"/><circle cx="2.3" cy="3.1" r=".9" className="robotFloorWheelV10"/>
              <rect x="1.6" y="-4.4" width="1.1" height="4.4" rx=".4" className="robotFloorMastV10"/>
              <line x1="2.4" y1="-1.3" x2="6.5" y2="-1.3" className="robotFloorForkV10"/>
              <line x1="2.4" y1=".1" x2="6.5" y2=".1" className="robotFloorForkV10"/>
              <text x="-1.4" y=".9" className="robotFloorTextV10">R</text>
              {robot?.carrying_box&&<rect x="6.1" y="-2.4" width="4.6" height="4.6" rx=".7" className="robotFloorBoxV10"/>}
            </g>
          </svg>
          <div className="floorReadoutV7"><div><small>NOW</small><b>{live?.floor_label||'Transfer zone'}</b></div><div><small>FROM → TO</small><b>{live?.source_code||decision?.chosen_source||'HOME'} → {live?.target_code||decision?.chosen_target||'HOME'}</b></div></div>
        </div>
        <div className="routeListV7">{activeFloorRoute.length?activeFloorRoute.map((n,i)=><div key={`${n.node_id}-${i}`} className={`${i===0?'start':''} ${i===activeFloorRoute.length-1?'end':''} ${i===nearestRouteIndex?'current':''}`}><span>{i===nearestRouteIndex?'▶':i+1}</span><div><b>{n.label}</b><small>{n.kind.replaceAll('_',' ')}</small></div></div>):<Empty text="No passage route is active."/>}</div>
      </Card>

      <Card className={`rackMotionCardV7 ${rackPhase?'active':''}`}>
        <div className="panelHeaderV7"><div><small>RACK CLOSE-UP</small><b>Rack {activeRack} · lift + fork movement</b></div><span>{rackPhase?'ACTIVE':'MONITOR'}</span></div>
        <div className={`rackCloseupV7 ${loadPhase?'loadingBox':unloadPhase?'unloadingBox':''}`}>
          <div className="rackAxisLabelsV7 cols" style={{gridTemplateColumns:`repeat(${maxCols},1fr)`}}>{columns.map(c=><span key={c}>C{c}</span>)}</div>
          <div className="rackAxisLabelsV7 levels" style={{gridTemplateRows:`repeat(${maxLevels},1fr)`}}>{levels.map(l=><span key={l}>L{l}</span>)}</div>
          <div className="rackCellsV7" style={{gridTemplateColumns:`repeat(${maxCols},1fr)`,gridTemplateRows:`repeat(${maxLevels},1fr)`}}>
            {levels.flatMap(level=>columns.map(col=>{
              const s=rackLookup.get(`${col}-${level}`)
              if(!s)return <div key={`${col}-${level}`} className="rackCellV7 missing"/>
              const source=s.code===(live?.source_code||decision?.chosen_source)
              const target=s.code===(live?.target_code||decision?.chosen_target)
              const pushing=(loadPhase&&source)||(unloadPhase&&target)
              return <button key={s.id} onClick={()=>setSelected(s)} className={`rackCellV7 ${slotClass(s)} ${source?'source':''} ${target?'target':''} ${pushing?'shelfPush':''} ${selected?.id===s.id?'selected':''}`} title={s.code}>{s.box?<><b>{s.box.code}</b><small>{s.box.quantity}</small></>:null}</button>
            }))}
          </div>
          {(loadPhase||unloadPhase)&&handledBox&&<div className="fallingBoxV12" style={{left:`${movingBoxLeft}%`,top:`${movingBoxTop}%`}}><b>{handledBox.code}</b><small>{loadPhase?'falling to forks':'placed on shelf'}</small></div>}
          <div className="rackCraneV7" style={{left:`${liftX}%`}}><i/><div className="rackCarriageV7" style={{top:`${liftY}%`}}><span>R</span><em className={Math.abs(robot?.y||0)>.05?'extended':''}/>{robot?.carrying_box&&<strong>BOX</strong>}</div></div>
        </div>
        <div className="rackMotionReadoutV7"><div><small>RACK PHASE</small><b>{rackPhase?live?.phase.replaceAll('_',' '):'Robot is in passage / transfer lane'}</b></div><div><small>SHELF TRANSFER</small><b>{loadPhase?'Box dropping to robot':unloadPhase?'Robot loading shelf':'Waiting'}</b></div><div><small>LIFT Z</small><b>{robot?.z?.toFixed?.(2)??'0.00'} m</b></div><div><small>FORK Y</small><b>{robot?.y?.toFixed?.(2)??'0.00'} m</b></div></div>
      </Card>

      <div className="simSideV7">
        <Card className="pathFollowerCardV9">
          <div className="panelHeaderV7"><div><small>PATH FOLLOWER</small><b>{live?.active?'Robot following route':'Waiting for route'}</b></div><span>{activeFloorRoute.length} nodes</span></div>
          <div className="pathFollowerHero"><small>CURRENT POSITION</small><b>{live?.floor_label||currentNode?.label||'Standby'}</b><span>{live?.active?'The robot is moving on the planned path automatically.':'No movement in progress.'}</span></div>
          <div className="pathFollowerGrid">
            <div><small>Current node</small><b>{currentNode?.label||'—'}</b></div>
            <div><small>Next node</small><b>{nextNode?.label||'—'}</b></div>
            <div><small>Route</small><b>{live?.source_code||decision?.chosen_source||'HOME'} → {live?.target_code||decision?.chosen_target||'HOME'}</b></div>
            <div><small>Lane</small><b>{rawStage.includes('TRANSFER')?'Transfer lane':rawStage.includes('PASSAGE')?'Passage':'Rack / station'}</b></div>
          </div>
        </Card>
        <Card>
          <div className="panelHeaderV7"><div><small>CURRENT DECISION</small><b>{decision?.decision_type?.replaceAll('_',' ')||'Waiting for work'}</b></div>{decision&&<span>{Math.round((decision.confidence||0)*100)}% confidence</span>}</div>
          {decision?<><div className="decisionHeroV7"><small>WHY THIS MOVE?</small><b>{decision.chosen_source||'HOME'} → {decision.chosen_target||'HOME'}</b><span>{decision.task_type.replaceAll('_',' ')}</span></div><div className="reasonListV7">{decision.reasons?.slice(0,4).map((r,i)=><div key={i}><span>{r.weight}</span><div><b>{r.label}</b><small>{r.value}</small></div></div>)}</div></>:<Empty text="The next intelligent decision appears here."/>}
        </Card>
        <Card>
          <div className="panelHeaderV7"><div><small>ACTIVE QUEUE</small><b>{data?.task_queue?.length||0} robot tasks</b></div></div>
          <div className="miniQueueV7">{(data?.task_queue||[]).slice(0,6).map((t:any,i:number)=><div key={t.id} className={t.id===decision?.task_id?'active':''}><span>{i+1}</span><div><b>{t.type.replaceAll('_',' ')}</b><small>{t.source||'HOME'} → {t.target||'HOME'}</small></div><Status value={t.status}/></div>)}{!data?.task_queue?.length&&<Empty text="Queue is empty."/>}</div>
        </Card>
      </div>
    </div>

    <div className="orderSectionV7">
      <Card>
        <div className="panelHeaderV7"><div><small>ORDER MOVEMENT TIMELINE</small><b>{execution.data?.request?`${execution.data.request.core_type} × ${execution.data.request.requested_quantity}`:'Inbound task or no production order'}</b></div>{execution.data?.request&&<Status value={execution.data.request.status}/>}</div>
        {execution.data?.tasks?.length?<div className="executionTimelineV7">{execution.data.tasks.map((t:any,i:number)=><div key={t.task_id} className={t.task_id===decision?.task_id?'active':''}><span>{i+1}</span><div><b>{t.task_type.replaceAll('_',' ')}</b><small>{t.chosen_source||'HOME'} → {t.chosen_target||'HOME'}</small></div><Status value={t.status}/></div>)}</div>:<Empty text="Production-order tasks will appear here. Inbound-package movement is visible in the live queue above."/>}
      </Card>
      <Card title="LOCATION / TRANSFER INSPECTOR">{selected?<div className="selectedLocationV7"><div><b>{selected.code}</b><Status value={selected.box?.status||selected.status}/></div><p>{selected.rack_face?`Rack ${selected.rack_face} · Column ${selected.column} · Level ${selected.level}`:'Transfer station'}</p><strong>{selected.box?`${selected.box.code} · ${selected.box.core_type} · ${selected.box.quantity} pcs`:'Empty / available'}</strong></div>:<div className="transferButtonsV7">{specials.map(s=><button key={s.id} onClick={()=>setSelected(s)}><b>{s.code}</b><small>{s.box?`${s.box.code} · ${s.box.quantity} pcs`:'Available'}</small></button>)}</div>}</Card>
    </div>
  </>
}
