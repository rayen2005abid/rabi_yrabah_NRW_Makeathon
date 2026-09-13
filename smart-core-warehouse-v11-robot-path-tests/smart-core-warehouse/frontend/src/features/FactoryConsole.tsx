import {useEffect,useMemo,useRef,useState} from 'react'
import {Link} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {get,post} from '../api/client'
import {Card,ErrorBox,Notice,PageHeader,Status} from '../components/Common'

export default function FactoryConsole(){
  const qc=useQueryClient()
  const videoRef=useRef<HTMLVideoElement|null>(null)
  const canvasRef=useRef<HTMLCanvasElement|null>(null)
  const streamRef=useRef<MediaStream|null>(null)
  const weightsRef=useRef<number[]>([])
  const armedRef=useRef(true)
  const liveVisionPendingRef=useRef(false)
  const [cameraOn,setCameraOn]=useState(false)
  const [autoCapture,setAutoCapture]=useState(false)
  const [imageData,setImageData]=useState<string|null>(null)
  const [liveVision,setLiveVision]=useState<any>(null)
  const [liveVisionError,setLiveVisionError]=useState<string|null>(null)
  const [confirmedAnalysis,setConfirmedAnalysis]=useState<any>(null)
  const [demoPieces,setDemoPieces]=useState(24)
  const [showSecretSteps,setShowSecretSteps]=useState(false)
  const [core,setCore]=useState('CORE-A')
  const [qty,setQty]=useState(30)

  const cores=useQuery({queryKey:['factoryCores'],queryFn:()=>get<any[]>('/core-types')})
  const station=useQuery({queryKey:['captureStation'],queryFn:()=>get<any>('/capture/station'),refetchInterval:400})
  const twin=useQuery({queryKey:['factoryTwin'],queryFn:()=>get<any>('/digital-twin'),refetchInterval:500})
  const alerts=useQuery({queryKey:['factoryAlerts'],queryFn:()=>get<any[]>('/alerts'),refetchInterval:2500})

  useEffect(()=>()=>{streamRef.current?.getTracks().forEach(t=>t.stop())},[])
  useEffect(()=>{if(cores.data?.length&&!cores.data.some(c=>c.code===core))setCore(cores.data[0].code)},[cores.data,core])

  const startCamera=async()=>{
    try{
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false})
      streamRef.current=stream
      if(videoRef.current){videoRef.current.srcObject=stream;await videoRef.current.play()}
      setCameraOn(true)
    }catch{setCameraOn(false)}
  }

  useEffect(()=>{
    const canUseCamera = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
    if(canUseCamera)startCamera()
  },[])

  const frameFromVideo=()=>{
    const video=videoRef.current, canvas=canvasRef.current
    if(!video||!canvas||!video.videoWidth)return imageData
    canvas.width=640;canvas.height=Math.max(360,Math.round(640*video.videoHeight/video.videoWidth))
    canvas.getContext('2d')?.drawImage(video,0,0,canvas.width,canvas.height)
    const data=canvas.toDataURL('image/jpeg',.82);setImageData(data);return data
  }

  const classifyLiveImage=async(image:string|null)=>{
    if(!image||liveVisionPendingRef.current)return
    liveVisionPendingRef.current=true
    try{
      const result=await post<any>('/capture/classify',{image_data_url:image})
      setLiveVision(result.classification)
      setLiveVisionError(null)
    }catch(e:any){
      setLiveVisionError(e?.message||'CV unavailable')
    }finally{
      liveVisionPendingRef.current=false
    }
  }

  useEffect(()=>{
    if(!cameraOn&&!imageData)return
    const tick=()=>{const image=frameFromVideo()||imageData;classifyLiveImage(image)}
    tick()
    const id=window.setInterval(tick,1800)
    return ()=>window.clearInterval(id)
  },[cameraOn,imageData])

  const processCapture=useMutation({
    mutationFn:async(payload:{image:string|null;weight:number;coreType?:string;autoRegister?:boolean})=>post<any>('/capture/analyze',{image_data_url:payload.image,gross_weight_kg:payload.weight,demo_core_type:payload.coreType,auto_register:payload.autoRegister??true}),
    onSuccess:(data)=>{armedRef.current=false;setConfirmedAnalysis(data.analysis||data);qc.invalidateQueries()},
  })

  const manualCapture=()=>{
    const weight=Number(station.data?.weight_kg||0)
    const image=frameFromVideo()||imageData
    if(weight>0)processCapture.mutate({image,weight,coreType:confirmedCoreType||undefined,autoRegister:true})
  }

  const mapCvTypeToCore=(label?:string|null)=>{
    if(!label)return ''
    const direct=readyCores.find(c=>c.code===label)?.code
    if(direct)return direct
    const match=label.match(/TYPE_([A-E])$/i)
    return match?`CORE-${match[1].toUpperCase()}`:label
  }

  const confirmDetectedType=async()=>{
    const detected=confirmedCoreType
    const profile=detected?station.data?.profiles?.[detected]:null
    if(!detected||!profile)return
    const weight=Number((Number(profile.tare_weight_kg||0)+Number(profile.unit_weight_kg||0)*demoPieces).toFixed(3))
    await post('/capture/station/demo-weight',{weight_kg:weight})
    const image=frameFromVideo()||imageData
    processCapture.mutate({image,weight,coreType:detected,autoRegister:false})
  }

  useEffect(()=>{
    const w=Number(station.data?.weight_kg||0)
    weightsRef.current=[...weightsRef.current.slice(-4),w]
    if(w<0.25){armedRef.current=true;return}
    if(!autoCapture||!armedRef.current||processCapture.isPending)return
    const h=weightsRef.current
    if(h.length<4)return
    const stable=Math.max(...h)-Math.min(...h)<0.04
    if(stable&&w>1.0){
      const image=frameFromVideo()||imageData
      if(image||station.data?.source==='DEMO_SCALE')processCapture.mutate({image,weight:w})
    }
  },[station.data?.weight_kg,autoCapture,imageData,processCapture.isPending])

  const onFile=(file?:File)=>{
    if(!file)return
    const reader=new FileReader();reader.onload=()=>{const data=String(reader.result);setImageData(data);classifyLiveImage(data)};reader.readAsDataURL(file)
  }

  const production=useMutation({
    mutationFn:async()=>{
      const r=await post<any>('/production/requests',{core_type_code:core,requested_quantity:qty,priority:30})
      const p=await post<any>(`/production/requests/${r.id}/plan`)
      const s=await post<any>(`/production/requests/${r.id}/simulate`)
      if(s.status!=='PASS')return {request:r,plan:p,simulation:s,executed:false}
      const e=await post<any>(`/production/requests/${r.id}/execute`)
      return {request:r,plan:p,simulation:s,execution:e,executed:true}
    },
    onSuccess:()=>qc.invalidateQueries(),
  })

  const activeAlerts=(alerts.data||[]).filter(a=>a.active)
  const live=twin.data?.live_execution
  const decision=twin.data?.decision
  const capture=processCapture.data
  const readyCores=useMemo(()=>cores.data?.filter(c=>c.active)||[],[cores.data])
  const visibleType=liveVision?.core_type_code||liveVision?.core_type||capture?.analysis?.core_type
  const confirmedCoreType=mapCvTypeToCore(visibleType)
  const visibleConfidence=Number(liveVision?.confidence??capture?.analysis?.type_confidence??0)
  const visibleProfile=confirmedCoreType?station.data?.profiles?.[confirmedCoreType]:null
  const visibleCore=readyCores.find(c=>c.code===confirmedCoreType)
  const analysis=confirmedAnalysis||capture?.analysis
  const systemState=activeAlerts.length?'ATTENTION':live?.active?'ROBOT MOVING':'READY'
  const autoModeText=autoCapture?'ARMED':'PAUSED'
  const plannedItems=production.data?.plan?.items||[]

  useEffect(()=>{
    const onKey=(e:KeyboardEvent)=>{
      const target=e.target as HTMLElement|null
      const editing=target&&['INPUT','TEXTAREA','SELECT','BUTTON'].includes(target.tagName)
      if(editing)return
      if(e.code==='Space'){
        e.preventDefault()
        setShowSecretSteps(true)
      }
      if(e.code==='Escape')setShowSecretSteps(false)
    }
    window.addEventListener('keydown',onKey)
    return()=>window.removeEventListener('keydown',onKey)
  },[])

  return <>
    <PageHeader title="Factory Console" subtitle="A simple operator view for the factory: boxes enter automatically, the system identifies the type, estimates quantity, chooses a slot and dispatches the robot." actions={<><Link className="btn secondary" to="/digital-twin">Live warehouse</Link><Link className="btn secondary" to="/demo-showcase">Demo showcase</Link></>}/>

    <div className={`factoryStateBar ${activeAlerts.length?'warn':live?.active?'moving':'ready'}`}>
      <div><small>SYSTEM</small><b>{systemState}</b></div>
      <div><small>ROBOT</small><b>{twin.data?.robot?.mode||'OFFLINE'}</b></div>
      <div><small>CURRENT JOB</small><b>{decision?.box_code||decision?.task_type?.replaceAll('_',' ')||'None'}</b></div>
      <div><small>QUEUE</small><b>{twin.data?.task_queue?.length||0}</b></div>
      <div><small>ALERTS</small><b>{activeAlerts.length}</b></div>
    </div>

    <div className="factoryGrid factoryGridV9">
      <Card className="entryHeroCard">
        <div className="entryHeroTop">
          <div>
            <small>AUTOMATIC ENTRY</small>
            <b>Inbound capture station</b>
            <p>The camera proposes the type first. The operator confirms it, then the calibrated demo scale explains how the system calculates the number of pieces.</p>
          </div>
          <div className="entryHeroBadge"><span>{autoModeText}</span><Status value={processCapture.isPending?'PROCESSING':capture?.status||'READY'}/></div>
        </div>

        <div className="entryFlowStrip">
          {['Box arrives','Image captured','Type + quantity','Smart slot','Robot stores'].map((label,i)=><div key={label} className={capture&&i<5?'done':i===0?'active':''}><span>{i+1}</span><b>{label}</b></div>)}
        </div>

        <div className="entryWorkspaceGrid">
          <div className="entryCameraStage">
            <div className="entryStageHead"><b>Live camera</b><small>{cameraOn?'Camera active':'Fallback photo mode'}</small></div>
            <div className="cameraStageFrame">
              <video ref={videoRef} muted playsInline className={cameraOn?'cameraLive':'cameraLive off'}/>
              {!cameraOn&&imageData&&<img src={imageData} className="cameraStill" alt="Captured core"/>}
              {!cameraOn&&!imageData&&<div className="cameraPlaceholder"><b>Camera station</b><span>Start the camera or use a phone/photo input.</span></div>}
              <canvas ref={canvasRef} hidden/>
              <div className="cameraOverlayTag">{liveVisionPendingRef.current?'CV READING':'LIVE CV'}</div>
            </div>
            <div className="cameraActions entryActions"><button className="secondary" onClick={startCamera}>{cameraOn?'Camera active':'Start camera'}</button><label className="fileCaptureBtn">Photo<input type="file" accept="image/*" capture="environment" onChange={e=>onFile(e.target.files?.[0])}/></label></div>
          </div>

          <div className="entryStatusBoard">
            <div className="entryMetric main"><small>LIVE SCALE</small><b>{Number(station.data?.weight_kg||0).toFixed(2)} kg</b><span>{station.data?.source||'SCALE'}</span></div>
            <div className="entryMetric main"><small>LIVE CV TYPE</small><b>{confirmedCoreType||visibleType||'Looking...'}</b><span>{liveVisionError?`CV warning: ${liveVisionError}`:visibleType?`${Math.round(visibleConfidence*100)}% · ${liveVision?.source||'CV'}${confirmedCoreType!==visibleType?` · mapped from ${visibleType}`:''}`:'Camera frames are sent to CV continuously'}</span></div>
            <div className="entryMetric"><small>AUTOMATION</small><b>{autoCapture?'Enabled':'Manual'}</b><span>{autoCapture?'Waiting for stable weight':'Operator triggered'}</span></div>
            <div className="entryMetric"><small>CONFIRMED TYPE</small><b>{analysis?.core_type||'—'}</b><span>{analysis?`${Math.round((analysis?.type_confidence||0)*100)}% confidence`:'Press confirm when CV type is correct'}</span></div>
            <div className="entryMetric"><small>ESTIMATED COUNT</small><b>{analysis?.quantity?`${analysis.quantity} pcs`:'—'}</b><span>{analysis?.weight?.net_weight_kg?`${analysis.weight.net_weight_kg} kg net`:'Waiting for confirmed type + weight'}</span></div>
            <div className="entryMetric"><small>BOX ID</small><b>{capture?.box?.code||'Pending'}</b><span>{capture?.registered?'Registered automatically':'Will register after analysis'}</span></div>
            <div className="entryMetric"><small>DESTINATION</small><b>{capture?.robot_task?.target_location||'Pending'}</b><span>{capture?.registered?'Robot task queued':'No robot movement yet'}</span></div>
          </div>
        </div>

        <div className="cvConfirmPanelV13">
          <div className="cvDetectedCardV13">
            <small>MODEL RESULT</small>
            <b>{confirmedCoreType||visibleType||'No type yet'}</b>
            <span>{visibleType?'If this type is correct, confirm it and the system calculates quantity from weight.':'Hold the piece in the camera area.'}</span>
          </div>
          <div className="cvDetectedCardV13">
            <small>CHARACTERISTICS</small>
            <b>{visibleCore?.name||confirmedCoreType||visibleType||'—'}</b>
            <span>{visibleCore?.description||'Core profile appears after detection.'}</span>
          </div>
          <div className="cvWeightCalcV13">
            <label>Demo pieces<input type="number" min="1" value={demoPieces} onChange={e=>setDemoPieces(Math.max(1,Number(e.target.value)||1))}/></label>
            <div><small>DEMO WEIGHT</small><b>{visibleProfile?`${(Number(visibleProfile.tare_weight_kg||0)+Number(visibleProfile.unit_weight_kg||0)*demoPieces).toFixed(2)} kg`:'—'}</b><span>{visibleProfile?`tare ${visibleProfile.tare_weight_kg} + ${demoPieces} × ${visibleProfile.unit_weight_kg} kg`:'Waiting for detected type'}</span></div>
          </div>
          <button className="cvConfirmBtnV13" onClick={confirmDetectedType} disabled={!confirmedCoreType||!visibleProfile||processCapture.isPending}>{processCapture.isPending?'Calculating...':'Confirm CV type + calculate pieces'}</button>
        </div>
        {analysis&&<div className="cvFormulaResultV13">
          <div><small>FORMULA</small><b>Pieces = round((gross − tare) / unit)</b></div>
          <div><small>GROSS</small><b>{analysis.weight?.gross_weight_kg} kg</b></div>
          <div><small>TARE</small><b>{analysis.weight?.tare_weight_kg} kg</b></div>
          <div><small>UNIT</small><b>{analysis.weight?.unit_weight_kg} kg</b></div>
          <div><small>RESULT</small><b>{analysis.quantity} pieces</b></div>
        </div>}

        <label className="autoToggle autoToggleV9"><input type="checkbox" checked={autoCapture} onChange={e=>setAutoCapture(e.target.checked)}/><span><b>Automatic capture</b><small>When enabled, the system waits for a stable weight and triggers the full inbound flow automatically.</small></span></label>
        <div className="entryFooterActions"><button className="primaryWide" onClick={manualCapture} disabled={processCapture.isPending||Number(station.data?.weight_kg||0)<=0}>Process current box now</button><Link className="btn secondary" to="/digital-twin">Open robot path view</Link></div>
        <ErrorBox error={processCapture.error}/>
      </Card>

      <Card className="factoryProductionCard">
        <div className="factoryCardHead"><div><small>PRODUCTION DEMAND</small><b>Simple request panel</b></div><Status value={production.isPending?'PLANNING':production.data?.simulation?.status||'READY'}/></div>
        <label>Core type<select value={core} onChange={e=>setCore(e.target.value)}>{readyCores.map(c=><option key={c.id} value={c.code}>{c.code} — {c.name}</option>)}</select></label>
        <label>Quantity<input type="number" min="1" value={qty} onChange={e=>setQty(Math.max(1,Number(e.target.value)))}/></label>
        <div className="factoryQtyPresets"><button onClick={()=>setQty(20)}>20</button><button onClick={()=>{setCore('CORE-A');setQty(55)}}>55 FIFO demo</button><button onClick={()=>setQty(100)}>100</button></div>
        <button className="primaryWide factoryRunBtn" onClick={()=>production.mutate()} disabled={production.isPending}>{production.isPending?'System is deciding…':'Request production'}</button>
        <ErrorBox error={production.error}/>
        {production.data&&<div className="factoryDecisionSummary">
          <div><small>REQUEST</small><b>{core} × {qty}</b></div>
          <div><small>PLANNED</small><b>{production.data.plan?.total_planned??0}/{production.data.plan?.total_requested??qty}</b></div>
          <div><small>VALIDATION</small><Status value={production.data.simulation?.status||'UNKNOWN'}/></div>
          <div><small>ACTION</small><b>{production.data.executed?'Robot executing':'Not executed'}</b></div>
        </div>}
      </Card>

      <Card className="factoryOperationCard">
        <div className="factoryCardHead"><div><small>LIVE ROBOT OPERATION</small><b>{live?.active?live.phase?.replaceAll('_',' '):'Autonomous standby'}</b></div><span className="factoryProgressText">{Math.round((live?.progress||0)*100)}%</span></div>
        <div className="factoryProgress"><i style={{width:`${(live?.progress||0)*100}%`}}/></div>
        <div className="factoryOperationFacts"><div><small>BOX</small><b>{decision?.box_code||'—'}</b></div><div><small>FROM</small><b>{live?.source_code||decision?.chosen_source||'—'}</b></div><div><small>TO</small><b>{live?.target_code||decision?.chosen_target||'—'}</b></div><div><small>WHY</small><b>{decision?.reasons?.[0]?.label||'Waiting'}</b></div></div>
        <div className="robotPathMini">
          <div className="pathNode active"><span>1</span><b>Source</b></div>
          <i/>
          <div className="pathNode"><span>2</span><b>Passage</b></div>
          <i/>
          <div className="pathNode"><span>3</span><b>Transfer lane</b></div>
          <i/>
          <div className="pathNode"><span>4</span><b>Target</b></div>
        </div>
        <Link className="btn secondary fullBtn" to="/digital-twin">Open movement view</Link>
      </Card>

      <Card className="factoryAlertsCard">
        <div className="factoryCardHead"><div><small>OPERATOR ATTENTION</small><b>{activeAlerts.length?'Exceptions requiring attention':'Nothing to do'}</b></div></div>
        {activeAlerts.length?activeAlerts.slice(0,5).map(a=><div className="factoryAlertRow" key={a.id}><Status value={a.severity}/><div><b>{a.code.replaceAll('_',' ')}</b><small>{a.message}</small></div></div>):<Notice tone="success" title="Warehouse running normally"><span>The system is making decisions automatically. The operator only needs to create production demand or resolve an exception.</span></Notice>}
      </Card>
    </div>
    {showSecretSteps&&<div className="secretStepsOverlayV14" role="dialog" aria-modal="true">
      <div className="secretStepsPanelV14">
        <button className="secretCloseV14" onClick={()=>setShowSecretSteps(false)} aria-label="Close">×</button>
        <small>SECRET PRESENTATION MODE · SPACE</small>
        <h2>{core} × {qty} pieces</h2>
        <p>When this quantity is called, the system follows these steps in order.</p>
        <div className="secretStepGridV14">
          <div><span>1</span><b>Receive demand</b><em>Operator asks for {qty} pieces of {core}.</em></div>
          <div><span>2</span><b>Check drying rule</b><em>Only boxes that passed 24h drying are eligible.</em></div>
          <div><span>3</span><b>Apply FIFO</b><em>Oldest ready boxes are selected first.</em></div>
          <div><span>4</span><b>Calculate extraction</b><em>{plannedItems.length?`${plannedItems.length} box move${plannedItems.length===1?'':'s'} planned.`:'The planner calculates how many pieces to take from each box.'}</em></div>
          <div><span>5</span><b>Simulate route</b><em>A* path checks passage, rack access, robot safety and return slot.</em></div>
          <div><span>6</span><b>Move robot</b><em>Digital twin shows rack pickup, transfer lane, fork motion and box handoff.</em></div>
        </div>
        <div className="secretProofV14">
          <div><small>VALIDATION</small><b>{production.data?.simulation?.status||'READY TO PLAN'}</b></div>
          <div><small>FIFO PROOF</small><b>{plannedItems.length?plannedItems.map((i:any)=>`#${i.fifo_rank} ${i.source_slot}`).join(' → '):'Run request to show exact boxes'}</b></div>
          <div><small>ACTION</small><b>{production.data?.executed?'Robot executing':'Press Request production to launch'}</b></div>
        </div>
        <div className="secretActionsV14">
          <button onClick={()=>production.mutate()} disabled={production.isPending}>{production.isPending?'Planning...':'Request production now'}</button>
          <Link className="btn secondary" to="/digital-twin" onClick={()=>setShowSecretSteps(false)}>Open digital twin</Link>
        </div>
      </div>
    </div>}
  </>
}
