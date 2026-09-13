import {useEffect,useRef,useState} from 'react'
import {NavLink,Outlet} from 'react-router-dom'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {useWarehouseRealtime} from '../realtime/useWarehouseRealtime'

const links=[
  ['/','OP','Factory Console'],
  ['/dashboard','DB','Dashboard'],
  ['/digital-twin','LW','Robot Path & Tests'],
  ['/inventory','IV','Inventory'],
  ['/events','HS','History'],
  ['/demo-showcase','DS','Demo Showcase'],
  ['/admin','AD','Admin Panel'],
]

export default function Layout(){
  useWarehouseRealtime()
  const qc=useQueryClient()
  const [open,setOpen]=useState(false)
  const cycling=useRef(false)
  const health=useQuery({queryKey:['layoutHealth'],queryFn:()=>get<any>('/health'),refetchInterval:10000,retry:1})
  const robot=useQuery({queryKey:['layoutRobot'],queryFn:()=>get<any>('/robot/state'),refetchInterval:1200,retry:1})
  const demo=useQuery({queryKey:['layoutDemo'],queryFn:()=>get<any>('/demo/status'),refetchInterval:10000,retry:1})
  const twin=useQuery({queryKey:['layoutTwin'],queryFn:()=>get<any>('/digital-twin'),refetchInterval:1500,retry:1})
  const connected=health.isSuccess

  // The control loop lives at layout level, so the robot stays autonomous even
  // when the operator navigates away from the Digital Twin screen.
  useEffect(()=>{
    if(!connected)return
    let stopped=false
    const timer=window.setInterval(async()=>{
      if(stopped||cycling.current)return
      cycling.current=true
      try{
        await post('/digital-twin/auto-cycle')
        qc.invalidateQueries({queryKey:['twin']})
        qc.invalidateQueries({queryKey:['layoutTwin']})
        qc.invalidateQueries({queryKey:['adminTwin']})
        qc.invalidateQueries({queryKey:['requestExecution']})
      }catch{/* connection state is already visible in the shell */}
      finally{cycling.current=false}
    },120)
    return()=>{stopped=true;window.clearInterval(timer)}
  },[connected,qc])

  const mode=twin.data?.autonomy?.mode||'AUTO'
  return <div className="app appLiteNav">
    <button className="mobileMenu" onClick={()=>setOpen(v=>!v)} aria-label="Toggle navigation">☰</button>
    <aside className={open?'open':''}>
      <div className="brand sopalBrand">
        <img src="/sopal-tec.png" alt="SOPAL TEC" className="sopalLogo"/>
        <div className="brandSystem"><strong>Smart Core Warehouse</strong><small>SOPAL TEC autonomous warehouse control</small></div>
      </div>
      <nav className="singleNavGroup">
        {links.map(([to,icon,label])=><NavLink key={to} to={to} end={to==='/' } onClick={()=>setOpen(false)} className={({isActive})=>isActive?'active':''}><span className="navIcon">{icon}</span><span>{label}</span></NavLink>)}
      </nav>
      <div className="sideFoot compact">
        <div className="connectionLine"><span className={`dot ${connected?'ok':'bad'}`}/><b>{connected?'Backend connected':'Backend offline'}</b></div>
        <small>{demo.data?.boxes??0} demo boxes · {demo.data?.free_storage_slots??'—'} free slots</small>
        <small>Autonomy: {mode}</small>
      </div>
    </aside>
    <main>
      <header className="topbar">
        <div className="topbarTitle"><b>Smart Core Warehouse</b><span>Factory operations · autonomous capture · explainable robot control</span></div>
        <div className="topbarStatus">
          <div className="topbarChip"><small>Robot</small><b>{robot.data?.mode||'OFFLINE'}</b></div>
          <div className="topbarChip"><small>Control</small><b>{mode}</b></div>
          <div className={`systemBadge ${connected?'online':'offline'}`}><span/>{connected?'SYSTEM ONLINE':'OFFLINE'}</div>
        </div>
      </header>
      <section className="content"><Outlet/></section>
    </main>
  </div>
}
