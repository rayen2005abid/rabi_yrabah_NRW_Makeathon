import {useEffect,useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {Card,ErrorBox,PageHeader,Notice,Status} from '../components/Common'

export default function Intake(){
 const qc=useQueryClient();const cores=useQuery({queryKey:['cores'],queryFn:()=>get<any[]>('/core-types')})
 const [core,setCore]=useState('CORE-A');const [qty,setQty]=useState(30);const [confidence,setConfidence]=useState(.96)
 useEffect(()=>{if(cores.data?.length&&!cores.data.some(c=>c.code===core))setCore(cores.data[0].code)},[cores.data,core])
 const m=useMutation({mutationFn:()=>post<any>('/intake/from-cv',{core_type:core,quantity:qty,confidence,status:'ACCEPTED'}),onSuccess:()=>qc.invalidateQueries()})
 return <>
  <PageHeader title="New Box Intake" subtitle="Validate the external CV result, register the box, and let the backend choose its storage location."/>
  <div className="intakeLayout">
   <Card className="intakeCard"><div className="sectionLead"><span>CV</span><div><b>Mock computer-vision result</b><small>Same contract used by the future real CV HTTP gateway.</small></div></div><div className="formGrid"><label>Detected core type<select value={core} onChange={e=>setCore(e.target.value)}>{cores.data?.filter(c=>c.active).map(c=><option key={c.id}>{c.code}</option>)}</select></label><label>Detected quantity<input type="number" min="1" value={qty} onChange={e=>setQty(Number(e.target.value))}/></label><label>Confidence<input type="number" step=".01" min="0" max="1" value={confidence} onChange={e=>setConfidence(Number(e.target.value))}/></label></div><div className="confidenceBar"><i style={{width:`${Math.max(0,Math.min(100,confidence*100))}%`}}/><span>{Math.round(confidence*100)}%</span></div><button className="primaryWide" onClick={()=>m.mutate()} disabled={m.isPending}>{m.isPending?'Registering…':'Validate & register box'}</button><ErrorBox error={m.error}/></Card>
   <Card title="INTAKE RESULT">{m.data?<><Notice tone="success" title="Box accepted into warehouse control"><span>The box is registered with its original timestamp and a robot storage task is created automatically.</span></Notice><div className="resultFacts"><div><small>BOX</small><b>{m.data.code}</b></div><div><small>QUANTITY</small><b>{m.data.quantity}</b></div><div><small>STATUS</small><Status value={m.data.status}/></div><div><small>READY AT</small><b>{new Date(m.data.ready_at).toLocaleString()}</b></div></div></>:<div className="empty">No box registered in this session yet.</div>}</Card>
  </div>
 </>
}
