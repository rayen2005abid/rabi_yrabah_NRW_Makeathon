import type {ReactNode} from 'react'
import {statusClass} from '../domain/status'

export function Card({title,children,className=''}:{title?:string;children:ReactNode;className?:string}){
  return <div className={`card ${className}`}>{title&&<div className="cardTitle">{title}</div>}{children}</div>
}

export function Metric({label,value,sub,tone='default'}:{label:string;value:ReactNode;sub?:string;tone?:'default'|'good'|'warn'|'critical'}){
  return <Card className={`metricCard metric-${tone}`}><div className="metricLabel">{label}</div><div className="metricValue">{value}</div>{sub&&<div className="muted">{sub}</div>}</Card>
}

export function Status({value}:{value:string}){return <span className={`status ${statusClass(value)}`}>{value.replaceAll('_',' ')}</span>}
export function ErrorBox({error}:{error:any}){return error?<div className="error"><b>Action failed</b><span>{String(error.message||error)}</span></div>:null}
export function Empty({text='No data'}:{text?:string}){return <div className="empty">{text}</div>}

export function PageHeader({title,subtitle,eyebrow='SOPAL TEC WCS',actions}:{title:string;subtitle?:string;eyebrow?:string;actions?:ReactNode}){
  return <div className="pageHead pageHeadModern"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>{actions&&<div className="pageActions">{actions}</div>}</div>
}

export function Notice({tone='info',title,children}:{tone?:'info'|'success'|'warning'|'danger';title:string;children?:ReactNode}){
  return <div className={`notice notice-${tone}`}><div className="noticeMark"/><div><strong>{title}</strong>{children&&<div className="noticeBody">{children}</div>}</div></div>
}

export function ProgressSteps({steps}:{steps:{label:string;state:'done'|'active'|'idle'|'error'}[]}){
  return <div className="progressSteps">{steps.map((s,i)=><div key={s.label} className={`progressStep ${s.state}`}><span>{s.state==='done'?'✓':i+1}</span><b>{s.label}</b></div>)}</div>
}
