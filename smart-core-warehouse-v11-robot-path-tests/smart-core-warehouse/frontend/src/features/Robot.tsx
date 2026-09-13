import {useState} from 'react'
import {Link} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {Card,Metric,Status,ErrorBox,PageHeader,Empty} from '../components/Common'

export default function Robot(){
 const qc=useQueryClient();const [removed,setRemoved]=useState<number|null>(null)
 const r=useQuery({queryKey:['robot'],queryFn:()=>get<any>('/robot/state'),refetchInterval:1000})
 const t=useQuery({queryKey:['tasks'],queryFn:()=>get<any[]>('/robot/tasks'),refetchInterval:1500})
 const w=useQuery({queryKey:['warehouseRobot'],queryFn:()=>get<any>('/warehouse/state'),refetchInterval:1000})
 const proc=useMutation({mutationFn:()=>post('/robot/process-next'),onSuccess:()=>qc.invalidateQueries()})
 const ps=w.data?.picking_station;const suggested=ps?.pick_context?.suggested_quantity
 const actual=removed??suggested??0
 const pick=useMutation({mutationFn:()=>post(`/picking/${ps.slot.box.id}/confirm`,{actual_quantity_removed:actual}),onSuccess:()=>{setRemoved(null);qc.invalidateQueries()}})
 return <>
  <PageHeader title="Robot Monitor" subtitle="Hardware-facing state, task queue and picking confirmation." actions={<><Link className="btn secondary" to="/digital-twin">Open Digital Twin</Link><button onClick={()=>proc.mutate()}>Process next mock task</button></>}/>
  <div className="metrics"><Metric label="X position" value={r.data?.x?.toFixed?.(2)??0}/><Metric label="Z position" value={r.data?.z?.toFixed?.(2)??0}/><Metric label="Y fork" value={r.data?.y?.toFixed?.(2)??0}/><Metric label="Robot mode" value={r.data?.mode||'—'}/><Metric label="Carrying" value={r.data?.carrying_box?'YES':'NO'} tone={r.data?.carrying_box?'warn':'default'}/></div>
  <div className="grid2"><Card title="PICKING STATION">{ps?<><div className="planSummary"><span>{ps.slot?.code||'PICKING'}</span><Status value={ps.state}/></div>{ps.slot?.box?<><div className="pickBox"><span className="miniCode large">{ps.slot.box.code}</span><div><b>{ps.slot.box.core_type}</b><small>{ps.slot.box.quantity} pieces currently in box</small></div></div>{suggested!=null&&<div className="suggestedPick"><span>Planned FIFO removal</span><b>{suggested} pieces</b></div>}<label>Actual quantity removed<input type="number" min="0" max={ps.slot.box.quantity} value={actual} onChange={e=>setRemoved(Number(e.target.value))}/></label><button className="primaryWide" onClick={()=>pick.mutate()} disabled={pick.isPending}>Confirm pick</button><ErrorBox error={pick.error}/></>:<Empty text="No box at picking. The station is available."/>}</>:<Empty text="Loading station state."/>}</Card><Card title="EMBEDDED GATEWAY"><div className="embeddedState"><div><small>MODE</small><b>{r.data?.mode||'—'}</b></div><div><small>CURRENT TASK</small><b>{r.data?.current_task_id?.slice(0,8)||'None'}</b></div><div><small>FAULT</small><b className={r.data?.fault?'badText':''}>{r.data?.fault||'None'}</b></div><div><small>ESTOP</small><b>{r.data?.estop?'ACTIVE':'Clear'}</b></div></div></Card></div>
  <Card title="TASK QUEUE"><div className="responsiveTable"><table><thead><tr><th>Type</th><th>Source</th><th>Target</th><th>Status</th><th>Priority</th></tr></thead><tbody>{t.data?.slice(0,20).map(x=><tr key={x.id}><td><b>{x.type.replaceAll('_',' ')}</b></td><td>{x.source_location||'—'}</td><td>{x.target_location||'—'}</td><td><Status value={x.status}/></td><td>{x.priority}</td></tr>)}</tbody></table></div></Card>
 </>
}
