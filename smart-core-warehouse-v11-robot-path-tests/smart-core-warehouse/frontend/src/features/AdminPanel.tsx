import {useMemo,useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {Card,ErrorBox,Notice,PageHeader,Status,Empty} from '../components/Common'
import {get,post} from '../api/client'

export default function AdminPanel(){
  const qc=useQueryClient()
  const twin=useQuery({queryKey:['adminTwin'],queryFn:()=>get<any>('/digital-twin'),refetchInterval:300})
  const faults=useQuery({queryKey:['adminFaults'],queryFn:()=>get<any[]>('/faults'),refetchInterval:1500})
  const capture=useQuery({queryKey:['adminCapture'],queryFn:()=>get<any>('/capture/station'),refetchInterval:800})
  const [manualTarget,setManualTarget]=useState('')
  const [overrideTarget,setOverrideTarget]=useState('')
  const [demoWeight,setDemoWeight]=useState(0)
  const [pose,setPose]=useState({x:0,z:0,y:0,carrying_box:false})
  const activeFault=faults.data?.find(f=>f.active)
  const refresh=()=>qc.invalidateQueries()
  const robot=twin.data?.robot
  const live=twin.data?.live_execution
  const decision=twin.data?.decision
  const autonomy=twin.data?.autonomy?.mode||'AUTO'
  const task=twin.data?.task_queue?.find((t:any)=>t.id===decision?.task_id)||twin.data?.task_queue?.[0]
  const storage=useMemo(()=>((twin.data?.slots||[]) as any[]).filter(s=>s.type==='STORAGE'&&s.enabled!==false&&!['BLOCKED','MAINTENANCE','DISABLED'].includes(s.status)),[twin.data?.slots])
  const allTargets=useMemo(()=>((twin.data?.slots||[]) as any[]).filter(s=>s.enabled!==false&&!['BLOCKED','MAINTENANCE','DISABLED'].includes(s.status)),[twin.data?.slots])

  const setMode=useMutation({mutationFn:(mode:string)=>post<any>('/admin/autonomy/mode',{mode}),onSuccess:refresh})
  const run=useMutation({mutationFn:()=>post<any>('/digital-twin/run-next'),onSuccess:refresh})
  const stop=useMutation({mutationFn:()=>post<any>('/digital-twin/cancel'),onSuccess:refresh})
  const home=useMutation({mutationFn:()=>post<any>('/robot/home'),onSuccess:refresh})
  const reset=useMutation({mutationFn:()=>post<any>('/demo/reset'),onSuccess:refresh})
  const goTo=useMutation({mutationFn:()=>post<any>('/admin/robot/go-to',{slot_code:manualTarget}),onSuccess:()=>{setManualTarget('');refresh()}})
  const manualPose=useMutation({mutationFn:(next:any)=>post<any>('/admin/robot/manual-pose',{...next,mode:'MANUAL'}),onSuccess:r=>{setPose({x:r.robot.x,z:r.robot.z,y:r.robot.y,carrying_box:r.robot.carrying_box});refresh()}})
  const override=useMutation({mutationFn:()=>post<any>(`/admin/robot/tasks/${decision.task_id}/override-target`,{slot_code:overrideTarget}),onSuccess:()=>{setOverrideTarget('');refresh()}})
  const inject=useMutation({mutationFn:()=>post<any>('/faults/inject',{type:'Z_AXIS_FAULT',details:{source:'admin_panel'}}),onSuccess:refresh})
  const clear=useMutation({mutationFn:()=>{if(!activeFault)return Promise.reject(new Error('No active fault'));return post<any>(`/faults/${activeFault.id}/clear`)},onSuccess:refresh})
  const speed=useMutation({mutationFn:(multiplier:number)=>post<any>('/digital-twin/speed',{multiplier}),onSuccess:refresh})
  const setScale=useMutation({mutationFn:()=>post<any>('/capture/station/demo-weight',{weight_kg:demoWeight}),onSuccess:refresh})

  const canOverride=!!decision&&['RETURN_BOX','STORE_BOX','RECOVERY'].includes(decision.task_type)&&decision.status==='QUEUED'
  const syncPose=()=>setPose({x:Number(robot?.x||0),z:Number(robot?.z||0),y:Number(robot?.y||0),carrying_box:!!robot?.carrying_box})
  const clampPose=(next:any)=>({x:Math.max(0,Number(next.x)||0),z:Math.max(0,Number(next.z)||0),y:Math.max(0,Number(next.y)||0),carrying_box:!!next.carrying_box})
  const nudge=(axis:'x'|'z'|'y',delta:number)=>{const next=clampPose({...pose,[axis]:Number((Number((pose as any)[axis])+delta).toFixed(2))});setPose(next);manualPose.mutate(next)}

  return <>
    <PageHeader title="Admin Panel" subtitle="Supervise the intelligent system, inspect its reasoning, choose a destination when needed, or take manual control." actions={<Link className="btn secondary" to="/digital-twin">Open Live Warehouse</Link>}/>

    <div className="adminModeBarV6">
      <div><small>CONTROL MODE</small><b>{autonomy}</b><span>{autonomy==='AUTO'?'System decides and executes automatically.':autonomy==='SUPERVISED'?'System decides; admin starts the motion.':'Admin drives navigation and overrides.'}</span></div>
      <div>{['AUTO','SUPERVISED','MANUAL'].map(m=><button key={m} className={autonomy===m?'active':''} onClick={()=>setMode.mutate(m)} disabled={setMode.isPending}>{m}</button>)}</div>
    </div>

    <div className="adminGridV6">
      <Card className="adminDecisionV6">
        <div className="panelHeaderV6"><div><small>SYSTEM RECOMMENDATION</small><b>{decision?.decision_type?.replaceAll('_',' ')||'No active decision'}</b></div>{decision&&<span>{Math.round(decision.confidence*100)}% confidence</span>}</div>
        {decision?<>
          <div className="adminDecisionRouteV6"><div><small>SOURCE</small><b>{decision.chosen_source||'HOME'}</b></div><span>→</span><div><small>TARGET</small><b>{decision.chosen_target||'HOME'}</b></div></div>
          <div className="reasonListV6">{decision.reasons.map((r:any,i:number)=><div key={`${r.label}-${i}`}><span>{r.weight}%</span><div><b>{r.label}</b><small>{r.value}</small></div></div>)}</div>
        </>:<Empty text="No queued or running robot decision."/>}
      </Card>

      <Card className="adminControlsV6">
        <div className="panelHeaderV6"><div><small>MANUAL CONTROLS</small><b>Robot command</b></div><Status value={live?.active?'RUNNING':robot?.mode||'IDLE'}/></div>
        <div className="adminBtnGrid">
          <button onClick={()=>run.mutate()} disabled={run.isPending||!!live?.active}>Run next task</button>
          <button className="danger" onClick={()=>stop.mutate()} disabled={stop.isPending||!live?.active}>Stop movement</button>
          <button className="secondary" onClick={()=>home.mutate()} disabled={home.isPending}>Home robot</button>
          <button className="secondary" onClick={()=>reset.mutate()} disabled={reset.isPending||!!live?.active}>Reset demo</button>
        </div>
        <ErrorBox error={run.error||stop.error||home.error||reset.error}/>
      </Card>

      <Card className="manualDestinationV6">
        <div className="panelHeaderV6"><div><small>GO TO LOCATION</small><b>Admin navigation command</b></div></div>
        <p className="cardExplain">Choose a physical location. The backend creates a manual navigation task and still computes the safest A* passage route.</p>
        <label>Destination<select value={manualTarget} onChange={e=>setManualTarget(e.target.value)}><option value="">Choose location…</option>{allTargets.map((s:any)=><option key={s.id} value={s.code}>{s.code} · {s.type.replaceAll('_',' ')}</option>)}</select></label>
        <button className="primaryWide" onClick={()=>goTo.mutate()} disabled={!manualTarget||goTo.isPending}>{goTo.isPending?'Queueing…':'Send robot there'}</button>
        <ErrorBox error={goTo.error}/>
      </Card>

      <Card className="manualPoseV12">
        <div className="panelHeaderV6"><div><small>MANUAL POSITION FIX</small><b>Direct robot pose</b></div><Status value={manualPose.isPending?'MOVING':'READY'}/></div>
        <p className="cardExplain">Use this for recovery: move X along the rack, Z lift height, and Y fork extension. It cancels the live animation first so the pose stays where you put it.</p>
        <div className="poseReadoutV12"><div><small>X</small><b>{robot?.x?.toFixed?.(2)??'0.00'} m</b></div><div><small>Z</small><b>{robot?.z?.toFixed?.(2)??'0.00'} m</b></div><div><small>FORK</small><b>{robot?.y?.toFixed?.(2)??'0.00'} m</b></div><div><small>LOAD</small><b>{robot?.carrying_box?'BOX':'EMPTY'}</b></div></div>
        <div className="poseFieldsV12">
          <label>X position<input type="number" min="0" step="0.1" value={pose.x} onChange={e=>setPose(clampPose({...pose,x:e.target.value}))}/></label>
          <label>Z lift<input type="number" min="0" step="0.1" value={pose.z} onChange={e=>setPose(clampPose({...pose,z:e.target.value}))}/></label>
          <label>Fork Y<input type="number" min="0" step="0.05" value={pose.y} onChange={e=>setPose(clampPose({...pose,y:e.target.value}))}/></label>
        </div>
        <div className="jogGridV12">
          <button className="secondary" onClick={()=>nudge('z',0.2)}>Lift up</button>
          <button className="secondary" onClick={()=>nudge('x',-0.2)}>X −</button>
          <button className="secondary" onClick={()=>nudge('x',0.2)}>X +</button>
          <button className="secondary" onClick={()=>nudge('z',-0.2)}>Lift down</button>
          <button className="secondary" onClick={()=>nudge('y',0.05)}>Fork out</button>
          <button className="secondary" onClick={()=>nudge('y',-0.05)}>Fork in</button>
        </div>
        <label className="loadToggleV12"><input type="checkbox" checked={pose.carrying_box} onChange={e=>setPose({...pose,carrying_box:e.target.checked})}/><span>Robot is carrying a box</span></label>
        <div className="adminBtnGrid"><button onClick={()=>manualPose.mutate(clampPose(pose))} disabled={manualPose.isPending}>Apply exact position</button><button className="secondary" onClick={syncPose}>Use current robot pose</button></div>
        <ErrorBox error={manualPose.error}/>
      </Card>

      <Card className="overrideCardV6">
        <div className="panelHeaderV6"><div><small>OVERRIDE DESTINATION</small><b>{canOverride?'Queued target can be changed':'No overridable task selected'}</b></div></div>
        {canOverride?<>
          <p className="cardExplain">The intelligent system recommends <b>{decision.chosen_target}</b>. You can force another safe storage slot before the task starts.</p>
          <label>New target<select value={overrideTarget} onChange={e=>setOverrideTarget(e.target.value)}><option value="">Choose alternative…</option>{storage.filter((s:any)=>s.status==='FREE'||s.code===decision.chosen_target).map((s:any)=><option key={s.id} value={s.code}>{s.code}</option>)}</select></label>
          <button className="primaryWide" onClick={()=>override.mutate()} disabled={!overrideTarget||override.isPending}>Override target</button>
          <ErrorBox error={override.error}/>
        </>:<Empty text="Target override is allowed only for queued return, storage or manual-navigation tasks."/>}
      </Card>

      <Card className="candidateAdminV6">
        <div className="panelHeaderV6"><div><small>DESTINATION CANDIDATES</small><b>Placement optimization model</b></div></div>
        <div className="placementModelStripV15">
          <div><small>MODEL 1</small><b>Weighted slot score</b></div>
          <div><small>MODEL 2</small><b>Demand forecast</b></div>
          <div><small>MODEL 3</small><b>A* route cost</b></div>
          <div><small>MODEL 4</small><b>RL policy value</b></div>
        </div>
        {decision?.candidates?.length?<div className="candidateListV6">{decision.candidates.slice(0,8).map((c:any,i:number)=><div key={c.slot_code||c.box_code||i} className={c.selected||c.selected_for_task?'chosen':''}><span>#{c.rank||c.fifo_rank||i+1}</span><div><b>{c.slot_code||c.box_code}</b><small>{c.factors?`travel ${c.factors.travel?.toFixed?.(2)??'—'} · passage ${c.factors.passage_distance?.toFixed?.(2)??'—'} · RL ${Math.round((c.factors.rl_policy_value??0)*100)}%`:(c.reason||'FIFO candidate')}</small></div><strong>{c.score!=null?Math.round(c.score):''}</strong></div>)}</div>:<Empty text="No alternative destination scoring is needed for this task."/>}
      </Card>

      <Card className="adminCaptureStation">
        <div className="panelHeaderV6"><div><small>CAPTURE STATION</small><b>Demo scale / hardware integration</b></div><Status value={capture.data?.source||'SCALE'}/></div>
        <p className="cardExplain">Factory mode reads weight automatically. For a laptop demo, set the simulated scale here. In production, configure SCALE_BASE_URL and this manual control is not needed.</p>
        <div className="adminScaleRow"><div><small>CURRENT</small><b>{Number(capture.data?.weight_kg||0).toFixed(2)} kg</b></div><label>Demo weight<input type="number" min="0" step="0.01" value={demoWeight} onChange={e=>setDemoWeight(Number(e.target.value))}/></label></div>
        <div className="adminBtnGrid"><button onClick={()=>setScale.mutate()} disabled={setScale.isPending}>Apply demo weight</button><button className="secondary" onClick={()=>{setDemoWeight(0);post('/capture/station/demo-weight',{weight_kg:0}).then(refresh)}}>Clear scale</button></div>
        <ErrorBox error={setScale.error}/>
      </Card>

      <Card className="adminHealthV6">
        <div className="panelHeaderV6"><div><small>ROBOT / SAFETY</small><b>Telemetry & recovery</b></div></div>
        <div className="telemetryGrid"><div><small>X</small><b>{robot?.x?.toFixed?.(2)??'0.00'} m</b></div><div><small>Z</small><b>{robot?.z?.toFixed?.(2)??'0.00'} m</b></div><div><small>FORK Y</small><b>{robot?.y?.toFixed?.(2)??'0.00'} m</b></div><div><small>LOAD</small><b>{robot?.carrying_box?'YES':'NO'}</b></div></div>
        <div className="speedRowV6"><small>Playback</small>{[0.5,1,2,4,8,12,16].map(v=><button key={v} className={live?.playback_speed===v?'active':''} onClick={()=>speed.mutate(v)}>{v}×</button>)}</div>
        {activeFault?<Notice tone="danger" title={activeFault.type.replaceAll('_',' ')}><span>A real backend fault is active.</span></Notice>:<Notice tone="success" title="No active fault"><span>Dispatch safety checks are clear.</span></Notice>}
        <div className="adminBtnGrid"><button className="danger" onClick={()=>inject.mutate()} disabled={!!activeFault||inject.isPending}>Inject Z-axis fault</button><button className="secondary" onClick={()=>clear.mutate()} disabled={!activeFault||clear.isPending}>Clear fault</button></div>
        <ErrorBox error={inject.error||clear.error||speed.error}/>
      </Card>
    </div>
  </>
}
