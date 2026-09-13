import {useMemo,useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {get} from '../api/client'
import {Card,Status,PageHeader,Metric} from '../components/Common'

export default function Warehouse(){
 const q=useQuery({queryKey:['warehouseState'],queryFn:()=>get<any>('/warehouse/state'),refetchInterval:3000})
 const [selected,setSelected]=useState<any>(null);const [face,setFace]=useState(1);const [filter,setFilter]=useState('ALL')
 const storage=q.data?.slots?.filter((s:any)=>s.type==='STORAGE')||[]
 const faces=useMemo(()=>Array.from(new Set(storage.map((s:any)=>s.rack_face))).filter(Boolean).sort() as number[],[storage])
 const current=storage.filter((s:any)=>s.rack_face===face)
 const maxCol=Math.max(1,...current.map((s:any)=>s.column||1));const maxLevel=Math.max(1,...current.map((s:any)=>s.level||1))
 const visible=current.filter((s:any)=>filter==='ALL'||(filter==='OCCUPIED'?!!s.box:filter==='FREE'?!s.box&&s.status==='FREE':s.status===filter))
 const visibleIds=new Set(visible.map((s:any)=>s.id))
 const lookup=new Map(current.map((s:any)=>[`${s.column}-${s.level}`,s]))
 const occupied=storage.filter((s:any)=>s.box).length;const reserved=storage.filter((s:any)=>s.status.includes('RESERVED')).length;const blocked=storage.filter((s:any)=>['BLOCKED','MAINTENANCE','DISABLED'].includes(s.status)).length
 return <>
  <PageHeader title="Warehouse Map" subtitle="Config-driven rack geometry with fast face/status filtering and physical slot inspection."/>
  <div className="metrics warehouseMetrics"><Metric label="Storage locations" value={storage.length}/><Metric label="Occupied" value={occupied}/><Metric label="Free" value={storage.length-occupied-blocked}/><Metric label="Reserved" value={reserved} tone="warn"/><Metric label="Unavailable" value={blocked} tone={blocked?'critical':'default'}/></div>
  <div className="warehouseToolbar"><div className="segmented">{faces.map(f=><button key={f} className={face===f?'active':''} onClick={()=>setFace(f)}>Rack {f}</button>)}</div><div className="segmented statusFilter">{['ALL','OCCUPIED','FREE','RESERVED_FOR_RETURN','BLOCKED'].map(x=><button key={x} className={filter===x?'active':''} onClick={()=>setFilter(x)}>{x.replaceAll('_',' ')}</button>)}</div></div>
  <div className="gridWarehouse warehouseMapV2"><Card><div className="faceMapHeader"><b>RACK {face}</b><span>{current.filter((s:any)=>s.box).length}/{current.length} occupied</span><small>Top row = highest level</small></div><div className="warehouseFaceGrid" style={{gridTemplateColumns:`repeat(${maxCol},minmax(34px,1fr))`}}>{Array.from({length:maxLevel}).flatMap((_,ri)=>{const level=maxLevel-ri;return Array.from({length:maxCol}).map((__,ci)=>{const s:any=lookup.get(`${ci+1}-${level}`);if(!s)return <div className="warehouseCell missing" key={`${ci}-${level}`}/>;const dim=filter!=='ALL'&&!visibleIds.has(s.id);return <button key={s.id} title={`${s.code} · ${s.box?.code||s.status}`} className={`warehouseCell ${s.status.toLowerCase()} ${s.box?.status?.toLowerCase()||''} ${dim?'dimmed':''} ${selected?.id===s.id?'selected':''}`} onClick={()=>setSelected(s)}><span>{s.code.replace(`R${face}-`,'')}</span>{s.box?<><b>{s.box.code}</b><small>{s.box.quantity} pcs</small></>:<small>FREE</small>}</button>})})}</div></Card>
  <Card title="LOCATION INSPECTOR">{selected?<div className="slotDetail"><div className="inspectorTitle"><div><b>{selected.code}</b><small>Physical storage location</small></div><Status value={selected.box?.status||selected.status}/></div><dl><dt>Rack / column / level</dt><dd>{selected.rack_face} / {selected.column} / {selected.level}</dd><dt>Coordinates</dt><dd>X {selected.x} · Y {selected.y} · Z {selected.z}</dd><dt>Slot state</dt><dd>{selected.status.replaceAll('_',' ')}</dd>{selected.box&&<><dt>Box</dt><dd>{selected.box.code}</dd><dt>Core type</dt><dd>{selected.box.core_type}</dd><dt>Quantity</dt><dd>{selected.box.quantity} / {selected.box.initial_quantity}</dd><dt>Entered</dt><dd>{new Date(selected.box.entered_at).toLocaleString()}</dd><dt>Ready</dt><dd>{new Date(selected.box.ready_at).toLocaleString()}</dd><dt>FIFO age</dt><dd>{Math.max(0,Math.floor((Date.now()-new Date(selected.box.entered_at).getTime())/3600000))} h</dd></>}</dl></div>:<div className="empty">Select a slot to inspect its physical and inventory state.</div>}</Card></div>
 </>
}
