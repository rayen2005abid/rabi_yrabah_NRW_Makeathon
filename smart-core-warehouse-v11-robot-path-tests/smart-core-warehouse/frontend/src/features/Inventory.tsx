import {useMemo,useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {get} from '../api/client'
import {Card,Status,PageHeader,Metric,Empty} from '../components/Common'

export default function Inventory(){
 const q=useQuery({queryKey:['boxes'],queryFn:()=>get<any[]>('/boxes'),refetchInterval:4000});const cores=useQuery({queryKey:['cores'],queryFn:()=>get<any[]>('/core-types')})
 const [search,setSearch]=useState('');const [status,setStatus]=useState('ACTIVE');const [core,setCore]=useState('ALL')
 const coreMap=useMemo(()=>new Map((cores.data||[]).map(c=>[c.id,c.code])),[cores.data])
 const data=(q.data||[]).filter(b=>(!search||b.code.toLowerCase().includes(search.toLowerCase()))&&(core==='ALL'||coreMap.get(b.core_type_id)===core)&&(status==='ALL'||(status==='ACTIVE'?b.quantity>0:b.status===status)))
 const ready=(q.data||[]).filter(b=>b.status==='READY'&&b.quantity>0).length;const drying=(q.data||[]).filter(b=>b.status==='DRYING'&&b.quantity>0).length;const partial=(q.data||[]).filter(b=>b.quantity>0&&b.quantity<b.initial_quantity).length
 return <><PageHeader title="Inventory" subtitle="Searchable box inventory. Original timestamps remain immutable after every partial production pick."/>
 <div className="metrics warehouseMetrics"><Metric label="Total box records" value={q.data?.length??0}/><Metric label="Ready boxes" value={ready} tone="good"/><Metric label="Drying boxes" value={drying} tone="warn"/><Metric label="Partial boxes" value={partial}/><Metric label="Visible rows" value={data.length}/></div>
 <Card><div className="tableToolbar"><input placeholder="Search box code…" value={search} onChange={e=>setSearch(e.target.value)}/><select value={core} onChange={e=>setCore(e.target.value)}><option value="ALL">All core types</option>{cores.data?.map(c=><option key={c.id} value={c.code}>{c.code}</option>)}</select><select value={status} onChange={e=>setStatus(e.target.value)}><option value="ACTIVE">Active stock</option><option value="ALL">All records</option><option value="READY">Ready</option><option value="DRYING">Drying</option><option value="EMPTY">Empty</option><option value="FAULTED">Faulted</option></select></div>{data.length?<div className="responsiveTable"><table><thead><tr><th>Box</th><th>Core type</th><th>Quantity</th><th>Fill</th><th>Status</th><th>Original entry</th><th>Ready at</th><th></th></tr></thead><tbody>{data.map(b=><tr key={b.id}><td><b>{b.code}</b></td><td>{coreMap.get(b.core_type_id)||b.core_type_id.slice(0,8)}</td><td><b>{b.quantity}</b> / {b.initial_quantity}</td><td><div className="fillBar"><i style={{width:`${b.initial_quantity?b.quantity/b.initial_quantity*100:0}%`}}/></div></td><td><Status value={b.status}/></td><td>{new Date(b.entered_at).toLocaleString()}</td><td>{new Date(b.ready_at).toLocaleString()}</td><td><Link to={`/boxes/${b.id}`}>Inspect →</Link></td></tr>)}</tbody></table></div>:<Empty text="No boxes match the selected filters."/>}</Card></>}
