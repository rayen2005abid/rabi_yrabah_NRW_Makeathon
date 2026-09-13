from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.clock import clock, ClockMode
from app.core.schemas import *
from app.core.models import CoreType, Box, Slot, ProductionRequest, FulfillmentPlan, RobotTask, RobotTelemetry, Fault, DomainEvent, Alert
from app.core.enums import ProductionRequestStatus, RobotTaskStatus
from app.core.config import get_settings
from app.slotting.service import choose_best_slot
from app.catalog.service import list_core_types, get_by_code
from app.intake.service import register_box, register_from_cv
from app.warehouse.service import list_slots, generate_slots, get_slot_by_code
from app.fulfillment.service import build_plan, shortage_info
from app.simulation.service import simulate_request, what_if_production, what_if_time_advance, what_if_blocked_slot, what_if_robot_fault, what_if_near_full
from app.robot.service import queue_for_plan, process_next
from app.robot.runtime import robot_runtime
from app.safety.service import validate_dispatch
from app.embedded.adapters import mock_adapter
from app.picking.service import confirm_pick
from app.faults.service import inject_fault, clear_fault
from app.analytics.service import summary as analytics_summary
from app.digital_twin.service import state as twin_state
from app.digital_twin.runtime import live_twin
from app.drying.service import refresh_readiness, soon_to_be_ready
from app.events.service import emit
from app.system_configuration.service import public_configuration
from app.embedded.reconciliation import reconcile_position
from app.embedded.state import embedded_station
from app.predictive.service import current_predictions
from app.demand_forecasting.service import forecaster
from app.realtime.manager import manager
from app.demo.seed import seed_session, demo_summary
from app.demo.scenarios import list_scenarios, run_scenario, advance_scenario, scenario_runtime
from app.autonomy.runtime import autonomy
from app.intelligence.service import decision_for_task, request_execution_trace, manual_route_from_robot
from app.robot.planner import semantic_path
from app.capture_station.service import capture_station, analyze_capture, classify_capture, weight_profiles, current_weight

router = APIRouter()

def as_dict(obj):
    if obj is None: return None
    return {c.name:getattr(obj,c.name) for c in obj.__table__.columns}

def fail(status: int, exc: Exception):
    raise HTTPException(status_code=status, detail=str(exc))

@router.get('/health')
def health(): return {'status':'ok','service':'smart-core-warehouse'}

@router.get('/demo/status')
def demo_status(db:Session=Depends(get_db)):
    return demo_summary(db)

@router.post('/demo/reset')
def demo_reset(db:Session=Depends(get_db)):
    try:
        summary=seed_session(db, reset=True)
        scenario_runtime.reset()
        manager.publish_sync({'type':'DEMO_RESET','payload':summary})
        return {'status':'RESET','summary':summary}
    except Exception as e:
        fail(500,e)

@router.get('/demo/scenarios')
def demo_scenarios():
    return list_scenarios()

@router.post('/demo/scenarios/{scenario_id}/run')
def demo_run_scenario(scenario_id:str, db:Session=Depends(get_db)):
    try:
        result=run_scenario(db, scenario_id)
        manager.publish_sync({'type':'DEMO_SCENARIO_STARTED','payload':{'scenario_id':scenario_id}})
        return result
    except Exception as e:
        fail(400,e)

@router.get('/core-types')
def core_types(db:Session=Depends(get_db)): return [as_dict(x) for x in list_core_types(db, True)]

@router.post('/core-types')
def create_core_type(payload:CoreTypeCreate, db:Session=Depends(get_db)):
    if get_by_code(db,payload.code): raise HTTPException(409,'core type code already exists')
    obj=CoreType(**payload.model_dump()); db.add(obj); db.commit(); db.refresh(obj); return as_dict(obj)

@router.patch('/core-types/{core_id}/deactivate')
def deactivate_core(core_id:str, db:Session=Depends(get_db)):
    obj=db.get(CoreType,core_id)
    if not obj: raise HTTPException(404,'not found')
    obj.active=False; db.commit(); return as_dict(obj)

@router.get('/boxes')
def boxes(db:Session=Depends(get_db)):
    refresh_readiness(db)
    return [as_dict(x) for x in db.scalars(select(Box).order_by(Box.entered_at)).all()]

@router.get('/boxes/{box_id}')
def box_detail(box_id:str, db:Session=Depends(get_db)):
    b=db.get(Box,box_id)
    if not b: raise HTTPException(404,'box not found')
    history=[as_dict(e) for e in db.scalars(select(DomainEvent).where(DomainEvent.aggregate_id==box_id).order_by(DomainEvent.occurred_at)).all()]
    return {'box':as_dict(b),'history':history}

@router.post('/intake/register')
def intake_register(payload:IntakeRegister, db:Session=Depends(get_db)):
    try: return as_dict(register_box(db,**payload.model_dump()))
    except Exception as e: fail(400,e)

@router.post('/intake/from-cv')
def intake_from_cv(payload:CVInput, db:Session=Depends(get_db)):
    try: return as_dict(register_from_cv(db,payload.model_dump()))
    except Exception as e: fail(400,e)

@router.get('/capture/station')
async def capture_station_state():
    weight=await current_weight()
    return {**capture_station.snapshot(), **weight, 'profiles': weight_profiles()}

@router.post('/capture/station/demo-weight')
def capture_station_demo_weight(payload:DemoScaleInput):
    capture_station.demo_weight_kg=float(payload.weight_kg)
    return capture_station.snapshot()

@router.post('/capture/classify')
async def capture_classify(payload:CaptureClassifyInput):
    try:
        result=await classify_capture(payload.image_data_url,payload.demo_core_type)
        capture_station.last_result={'status':'LIVE_CLASSIFIED','classification':result}
        manager.publish_sync({'type':'cv.live_classified','payload':result})
        return {'status':'LIVE_CLASSIFIED','classification':result}
    except Exception as e:
        fail(400,e)

@router.post('/capture/analyze')
async def capture_analyze(payload:CaptureAnalyzeInput, db:Session=Depends(get_db)):
    try:
        result=await analyze_capture(payload.image_data_url,payload.gross_weight_kg,payload.demo_core_type)
        if not payload.auto_register or result['status']!='ACCEPTED':
            return {'status':'ANALYZED','analysis':result,'registered':False}
        box=register_from_cv(db,{
            'core_type':result['core_type'],
            'quantity':result['quantity'],
            'confidence':result['type_confidence'],
            'status':'ACCEPTED',
            'capture':{'weight':result['weight'],'count_confidence':result['count_confidence']},
        })
        task=db.scalar(select(RobotTask).where(RobotTask.box_id==box.id,RobotTask.status==RobotTaskStatus.QUEUED.value).order_by(RobotTask.created_at.desc()))
        capture_station.demo_weight_kg=0.0
        emit(db,'CAPTURE_STATION_ACCEPTED','box',box.id,{
            'core_type':result['core_type'],'quantity':result['quantity'],
            'type_confidence':result['type_confidence'],'count_confidence':result['count_confidence'],
        })
        db.commit()
        return {'status':'REGISTERED','analysis':result,'registered':True,'box':as_dict(box),'robot_task':as_dict(task)}
    except Exception as e:
        fail(400,e)

@router.post('/capture/demo-arrival')
async def capture_demo_arrival(payload:DemoCaptureArrival, db:Session=Depends(get_db)):
    try:
        profile=weight_profiles().get(payload.core_type)
        if not profile: raise ValueError('NO_WEIGHT_PROFILE')
        weight=float(profile.get('tare_weight_kg',0))+float(profile['unit_weight_kg'])*payload.quantity
        capture_station.demo_weight_kg=round(weight,3)
        result=await analyze_capture(None,weight,payload.core_type)
        box=register_from_cv(db,{
            'core_type':result['core_type'],'quantity':result['quantity'],
            'confidence':result['type_confidence'],'status':'ACCEPTED',
            'capture':{'weight':result['weight'],'count_confidence':result['count_confidence'],'demo':True},
        })
        task=db.scalar(select(RobotTask).where(RobotTask.box_id==box.id,RobotTask.status==RobotTaskStatus.QUEUED.value).order_by(RobotTask.created_at.desc()))
        capture_station.demo_weight_kg=0.0
        db.commit()
        return {'status':'REGISTERED','analysis':result,'box':as_dict(box),'robot_task':as_dict(task)}
    except Exception as e:
        fail(400,e)

@router.get('/warehouse/slots')
def warehouse_slots(db:Session=Depends(get_db)): return [as_dict(x) for x in list_slots(db)]

@router.get('/warehouse/state')
def warehouse_state(db:Session=Depends(get_db)): return twin_state(db)

@router.post('/warehouse/initialize')
def initialize_warehouse(force:bool=False, db:Session=Depends(get_db)):
    try: return {'created':generate_slots(db,force)}
    except Exception as e: fail(400,e)

@router.get('/warehouse/ready-soon')
def ready_soon(hours:float=24, db:Session=Depends(get_db)): return [as_dict(x) for x in soon_to_be_ready(db,hours)]

@router.post('/production/requests')
def create_request(payload:ProductionRequestCreate, db:Session=Depends(get_db)):
    core=get_by_code(db,payload.core_type_code)
    if not core: raise HTTPException(404,'core type not found')
    req=ProductionRequest(core_type_id=core.id,requested_quantity=payload.requested_quantity,status=ProductionRequestStatus.PENDING.value,priority=payload.priority)
    db.add(req); db.flush(); emit(db,'PRODUCTION_REQUEST_CREATED','production_request',req.id,{'quantity':payload.requested_quantity,'core_type':core.code}); db.commit(); return as_dict(req)

@router.get('/production/requests')
def requests(db:Session=Depends(get_db)): return [as_dict(x) for x in db.scalars(select(ProductionRequest).order_by(ProductionRequest.created_at.desc())).all()]

@router.get('/production/requests/{request_id}')
def request_detail(request_id:str, db:Session=Depends(get_db)):
    req=db.get(ProductionRequest,request_id)
    if not req: raise HTTPException(404,'request not found')
    plan=db.scalar(select(FulfillmentPlan).where(FulfillmentPlan.request_id==request_id).order_by(FulfillmentPlan.created_at.desc()))
    data={'request':as_dict(req),'plan':None,'items':[]}
    if plan:
        data['plan']=as_dict(plan); data['items']=[as_dict(i) for i in plan.items]; data['shortage']=shortage_info(db,req,plan)
    data['history']=[as_dict(e) for e in db.scalars(select(DomainEvent).where(DomainEvent.aggregate_id==request_id).order_by(DomainEvent.occurred_at)).all()]
    return data

@router.get('/production/requests/{request_id}/execution')
def request_execution(request_id:str, db:Session=Depends(get_db)):
    try:
        return request_execution_trace(db, request_id)
    except Exception as e:
        fail(404, e)

@router.post('/production/requests/{request_id}/plan')
def plan_request(request_id:str, db:Session=Depends(get_db)):
    req=db.get(ProductionRequest,request_id)
    if not req: raise HTTPException(404,'request not found')
    try:
        p=build_plan(db,req); return {'plan':as_dict(p),'items':[as_dict(i) for i in p.items],'shortage':shortage_info(db,req,p)}
    except Exception as e: fail(400,e)

@router.post('/production/requests/{request_id}/simulate')
def simulate(request_id:str, db:Session=Depends(get_db)):
    req=db.get(ProductionRequest,request_id)
    if not req: raise HTTPException(404,'request not found')
    try: return simulate_request(db,req)
    except Exception as e: fail(400,e)

@router.post('/production/requests/{request_id}/execute')
def execute(request_id:str, db:Session=Depends(get_db)):
    req=db.get(ProductionRequest,request_id)
    if not req: raise HTTPException(404,'request not found')
    plan=db.scalar(select(FulfillmentPlan).where(FulfillmentPlan.request_id==request_id).order_by(FulfillmentPlan.created_at.desc()))
    if not plan or plan.validation_state!='PASS': raise HTTPException(409,'execution requires a passing simulation')
    try:
        tasks=queue_for_plan(db,plan); return {'status':'QUEUED','tasks':[as_dict(t) for t in tasks]}
    except Exception as e: fail(409,e)

@router.post('/picking/{box_id}/confirm')
def pick(box_id:str,payload:ConfirmPick,db:Session=Depends(get_db)):
    box=db.get(Box,box_id)
    if not box: raise HTTPException(404,'box not found')
    try: return confirm_pick(db,box,payload.actual_quantity_removed)
    except Exception as e: fail(400,e)

@router.get('/robot/state')
def robot_state(): return mock_adapter.get_status()

@router.post('/embedded/telemetry')
def embedded_telemetry(payload:EmbeddedTelemetryInput):
    state=embedded_station.update(payload.model_dump(mode='json'))
    manager.publish_sync({'type':'embedded.telemetry','payload':state})
    return state

@router.get('/embedded/state')
def embedded_state():
    return embedded_station.snapshot()

@router.get('/robot/tasks')
def robot_tasks(db:Session=Depends(get_db)): return [as_dict(x) for x in db.scalars(select(RobotTask).order_by(RobotTask.created_at.desc())).all()]

@router.get('/robot/tasks/{task_id}/decision')
def robot_task_decision(task_id:str, db:Session=Depends(get_db)):
    task=db.get(RobotTask,task_id)
    if not task: raise HTTPException(404,'task not found')
    return decision_for_task(db,task)


@router.get('/robot/telemetry')
def robot_telemetry(limit:int=100, db:Session=Depends(get_db)):
    return [as_dict(x) for x in db.scalars(select(RobotTelemetry).order_by(RobotTelemetry.created_at.desc()).limit(limit)).all()]

@router.post('/robot/telemetry/reconcile')
def reconcile_telemetry(payload:TelemetryInput, db:Session=Depends(get_db)):
    task=db.get(RobotTask,payload.task_id)
    if not task: raise HTTPException(404,'task not found')
    target=db.scalar(select(Slot).where(Slot.code==task.target_location)) if task.target_location else None
    if not target: raise HTTPException(409,'task target not available for reconciliation')
    t=RobotTelemetry(task_id=task.id,state=payload.state,x=payload.x,y=payload.y,z=payload.z,carrying_box=payload.carrying_box,fault=payload.fault)
    db.add(t)
    result=reconcile_position({'x':target.x_coordinate,'y':0.0,'z':target.z_coordinate},{'x':payload.x,'y':payload.y,'z':payload.z})
    if not result['ok']:
        inject_fault(db,'POSITION_MISMATCH',{'task_id':task.id,'error_m':result['error_m']})
        task.status=RobotTaskStatus.INTERRUPTED.value; task.failure_reason='POSITION_MISMATCH'
    db.commit()
    return result

@router.post('/robot/process-next')
def robot_process_next(db:Session=Depends(get_db)):
    result=process_next(db)
    return result or {'status':'IDLE','detail':'no queued task'}

@router.post('/robot/home')
def robot_home(): return mock_adapter.home()

@router.post('/simulation/production-request')
def what_if(payload:WhatIfProduction, db:Session=Depends(get_db)):
    core=get_by_code(db,payload.core_type_code)
    if not core: raise HTTPException(404,'core type not found')
    return what_if_production(db,core.id,payload.quantity)

@router.post('/simulation/incoming-box')
def what_if_incoming(payload:WhatIfIncoming, db:Session=Depends(get_db)):
    core=get_by_code(db,payload.core_type_code)
    if not core: raise HTTPException(404,'core type not found')
    if payload.confidence < get_settings().cv_min_confidence:
        return {'status':'FAIL','reason':'LOW_CV_CONFIDENCE','threshold':get_settings().cv_min_confidence,'simulation_only':True}
    transient=Box(code='SIMULATION-ONLY',core_type_id=core.id,quantity=payload.quantity,initial_quantity=payload.quantity,entered_at=clock.now(),ready_at=clock.now(),status='REGISTERING')
    candidate=choose_best_slot(db,transient)
    return {'status':'PASS' if candidate else 'FAIL','reason':None if candidate else 'WAREHOUSE_FULL','proposed_slot':candidate.code if candidate else None,'simulation_only':True}


@router.post('/simulation/time/preview')
def time_preview(payload:WhatIfTime, db:Session=Depends(get_db)):
    return what_if_time_advance(db,payload.hours)

@router.post('/simulation/blocked-slot')
def blocked_slot_preview(payload:WhatIfBlockedSlot, db:Session=Depends(get_db)):
    return what_if_blocked_slot(db,payload.slot_code)

@router.post('/simulation/robot-fault')
def robot_fault_preview(payload:WhatIfRobotFault):
    return what_if_robot_fault(payload.type)

@router.post('/simulation/near-full')
def near_full_preview(payload:WhatIfNearFull, db:Session=Depends(get_db)):
    return what_if_near_full(db,payload.incoming_boxes)

@router.get('/configuration')
def configuration(): return public_configuration()

@router.get('/demand-forecast/{core_type_code}')
def demand_forecast(core_type_code:str, db:Session=Depends(get_db)):
    core=get_by_code(db,core_type_code)
    if not core: raise HTTPException(404,'core type not found')
    return forecaster.forecast(db,core.id)

@router.post('/simulation/time/advance')
def time_advance(payload:TimeAdvance, db:Session=Depends(get_db)):
    snap=clock.advance(payload.hours); changed=refresh_readiness(db); return {'mode':snap.mode,'now':snap.now,'boxes_became_ready':changed}

@router.post('/simulation/time/set')
def time_set(payload:TimeSet, db:Session=Depends(get_db)):
    snap=clock.set_time(payload.timestamp); changed=refresh_readiness(db); return {'mode':snap.mode,'now':snap.now,'boxes_became_ready':changed}

@router.post('/simulation/time/real')
def time_real():
    snap=clock.set_mode(ClockMode.REAL_TIME); return {'mode':snap.mode,'now':snap.now}

@router.post('/simulation/slot-block')
def sim_slot_block(payload:SlotBlock, db:Session=Depends(get_db)):
    slot=get_slot_by_code(db,payload.slot_code)
    if not slot: raise HTTPException(404,'slot not found')
    # This endpoint is an explicit demo fault action, unlike pure what-if endpoints.
    slot.status='BLOCKED' if payload.blocked else ('OCCUPIED' if slot.box_id else 'FREE'); db.commit(); return as_dict(slot)

@router.post('/faults/inject')
def faults_inject(payload:FaultInject,db:Session=Depends(get_db)):
    try: return as_dict(inject_fault(db,payload.type,payload.details))
    except Exception as e: fail(400,e)

@router.post('/faults/{fault_id}/clear')
def faults_clear(fault_id:str,db:Session=Depends(get_db)):
    try: return as_dict(clear_fault(db,fault_id))
    except Exception as e: fail(404,e)

@router.get('/faults')
def faults(db:Session=Depends(get_db)): return [as_dict(x) for x in db.scalars(select(Fault).order_by(Fault.raised_at.desc())).all()]

@router.get('/alerts')
def alerts(db:Session=Depends(get_db)): return [as_dict(x) for x in db.scalars(select(Alert).order_by(Alert.created_at.desc())).all()]

@router.get('/predictive/risks')
def predictive_risks(db:Session=Depends(get_db)):
    return current_predictions(db)

@router.get('/events')
def events(limit:int=200, db:Session=Depends(get_db)): return [as_dict(x) for x in db.scalars(select(DomainEvent).order_by(DomainEvent.occurred_at.desc()).limit(limit)).all()]

@router.get('/analytics/summary')
def analytics(db:Session=Depends(get_db)): return analytics_summary(db)

@router.get('/digital-twin')
def digital_twin(db:Session=Depends(get_db)):
    state=twin_state(db)
    state['autonomy']=autonomy.snapshot()
    active_task=db.get(RobotTask, live_twin.task_id) if live_twin.task_id else None
    if active_task is None:
        active_task=db.scalar(select(RobotTask).where(RobotTask.status.in_([
            RobotTaskStatus.QUEUED.value,RobotTaskStatus.RUNNING.value,RobotTaskStatus.DISPATCHED.value
        ])).order_by(RobotTask.priority,RobotTask.sequence_number,RobotTask.created_at))
    state['decision']=decision_for_task(db,active_task)
    return state


def _start_next_live_task(db:Session):
    if live_twin.active:
        return {'status':'RUNNING','live_execution':live_twin.snapshot()}
    if robot_runtime.current_task_id is not None:
        return {'status':'WAITING','reason':'ROBOT_BUSY','task_id':robot_runtime.current_task_id}
    task=db.scalar(select(RobotTask).where(RobotTask.status==RobotTaskStatus.QUEUED.value).order_by(RobotTask.priority,RobotTask.sequence_number,RobotTask.created_at))
    if not task:
        return {'status':'IDLE','detail':'no queued task'}
    source=db.scalar(select(Slot).where(Slot.code==task.source_location)) if task.source_location else None
    target=db.scalar(select(Slot).where(Slot.code==task.target_location)) if task.target_location else None
    if task.type=='RETRIEVE_BOX' and target and target.box_id is not None:
        return {'status':'WAITING','reason':'PICKING_STATION_OCCUPIED','task_id':task.id}
    safety=validate_dispatch(db,source,target,robot_runtime.carrying_box,allow_occupied_target=(task.type=='RECOVERY'))
    if not safety.ok:
        return {'status':'BLOCKED','reason':safety.reason,'task_id':task.id}
    snap=live_twin.start(task.id,source,target)
    manager.publish_sync({'type':'ROBOT_TELEMETRY','payload':{'task_id':task.id,'phase':snap['phase'],'progress':snap['progress']}})
    emit(db,'ROBOT_DECISION_ACCEPTED','robot_task',task.id,{'mode':autonomy.mode,'decision':decision_for_task(db,task)})
    db.commit()
    return {'status':'STARTED','task_id':task.id,'live_execution':snap,'decision':decision_for_task(db,task)}


def _tick_live_task(db:Session):
    if not live_twin.active:
        return {'status':'IDLE','live_execution':live_twin.snapshot(),'robot':robot_runtime.as_dict()}
    snap=live_twin.tick()
    task=db.get(RobotTask,live_twin.task_id) if live_twin.task_id else None
    db.add(RobotTelemetry(task_id=live_twin.task_id,state=snap['phase'],x=robot_runtime.x,y=robot_runtime.y,z=robot_runtime.z,carrying_box=robot_runtime.carrying_box,fault=robot_runtime.fault))
    db.commit()
    manager.publish_sync({'type':'ROBOT_TELEMETRY','payload':{'task_id':live_twin.task_id,'phase':snap['phase'],'progress':snap['progress'],'x':robot_runtime.x,'y':robot_runtime.y,'z':robot_runtime.z,'carrying_box':robot_runtime.carrying_box}})
    if snap['progress']>=1.0 and task:
        result=mock_adapter.dispatch_task(db,task)
        live_twin.finish_visual()
        return {'status':'COMPLETED','execution':result,'live_execution':live_twin.snapshot(),'robot':robot_runtime.as_dict()}
    return {'status':'RUNNING','live_execution':snap,'robot':robot_runtime.as_dict()}


def _auto_confirm_pick(db:Session):
    state=twin_state(db)
    picking=state.get('picking_station') or {}
    slot=picking.get('slot') or {}
    box_data=slot.get('box') if slot else None
    context=picking.get('pick_context') or {}
    qty=context.get('suggested_quantity')
    if picking.get('state')!='WAITING_CONFIRMATION' or not box_data or qty is None:
        return None
    box=db.get(Box,box_data['id'])
    if not box:
        return None
    result=confirm_pick(db,box,int(qty))
    return {'status':'PICK_CONFIRMED','result':result}


@router.post('/digital-twin/run-next')
def digital_twin_run_next(db:Session=Depends(get_db)):
    try:
        return _start_next_live_task(db)
    except Exception as e:
        fail(409,e)

@router.post('/digital-twin/tick')
def digital_twin_tick(db:Session=Depends(get_db)):
    return _tick_live_task(db)

@router.post('/digital-twin/auto-cycle')
def digital_twin_auto_cycle(db:Session=Depends(get_db)):
    """One autonomous control iteration.

    The UI only asks the backend to advance the control loop. The backend owns
    the decisions: finish the current motion, confirm the exact planned pick,
    then dispatch the next safe queued task when AUTO mode is enabled.
    """
    if live_twin.active:
        return {'mode':autonomy.mode,**_tick_live_task(db)}
    if not autonomy.auto_enabled:
        return {'mode':autonomy.mode,'status':'SUPERVISED_WAIT','state':digital_twin(db)}
    scenario_step=advance_scenario(db)
    if scenario_step:
        return {'mode':autonomy.mode,**scenario_step}
    confirmed=_auto_confirm_pick(db)
    if confirmed:
        return {'mode':autonomy.mode,**confirmed}
    started=_start_next_live_task(db)
    return {'mode':autonomy.mode,**started}

@router.post('/digital-twin/speed')
def digital_twin_speed(payload:TwinSpeed):
    try:
        return {'status':'UPDATED','live_execution':live_twin.set_speed(payload.multiplier)}
    except Exception as e:
        fail(400,e)

@router.post('/digital-twin/cancel')
def digital_twin_cancel():
    return {'status':'CANCELLED','live_execution':live_twin.cancel(),'robot':robot_runtime.as_dict()}


@router.get('/admin/autonomy')
def admin_autonomy():
    return autonomy.snapshot()

@router.post('/admin/autonomy/mode')
def admin_autonomy_mode(payload:AutonomyModeInput):
    try:
        return autonomy.set_mode(payload.mode)
    except Exception as e:
        fail(400,e)

@router.post('/admin/robot/go-to')
def admin_robot_go_to(payload:ManualRobotGoTo, db:Session=Depends(get_db)):
    target=get_slot_by_code(db,payload.slot_code)
    if not target: raise HTTPException(404,'target slot not found')
    if not target.enabled or target.status in {'BLOCKED','MAINTENANCE','DISABLED'}:
        raise HTTPException(409,'target location is unavailable')
    task=RobotTask(
        type='RECOVERY',priority=payload.priority,box_id=None,source_location=None,
        target_location=target.code,status=RobotTaskStatus.QUEUED.value,sequence_number=0,
        request_id=None,planned_path=manual_route_from_robot(target,robot_runtime.x,robot_runtime.z),
    )
    db.add(task); db.flush()
    emit(db,'ADMIN_ROBOT_NAVIGATION','robot_task',task.id,{'target':target.code,'mode':autonomy.mode})
    db.commit(); db.refresh(task)
    return {'status':'QUEUED','task':as_dict(task),'decision':decision_for_task(db,task)}

@router.post('/admin/robot/manual-pose')
def admin_robot_manual_pose(payload:ManualRobotPose, db:Session=Depends(get_db)):
    if live_twin.active:
        live_twin.cancel()
    robot_runtime.x = float(payload.x)
    robot_runtime.y = float(payload.y)
    robot_runtime.z = float(payload.z)
    if payload.carrying_box is not None:
        robot_runtime.carrying_box = bool(payload.carrying_box)
    if not robot_runtime.estop and not robot_runtime.fault:
        robot_runtime.mode = payload.mode.upper()[:30] or 'MANUAL'
    db.add(RobotTelemetry(task_id=None,state='ADMIN_MANUAL_POSE',x=robot_runtime.x,y=robot_runtime.y,z=robot_runtime.z,carrying_box=robot_runtime.carrying_box,fault=robot_runtime.fault))
    emit(db,'ADMIN_ROBOT_MANUAL_POSE','robot',None,{'x':robot_runtime.x,'y':robot_runtime.y,'z':robot_runtime.z,'carrying_box':robot_runtime.carrying_box})
    db.commit()
    snap=robot_runtime.as_dict()
    manager.publish_sync({'type':'ROBOT_MANUAL_POSE','payload':snap})
    return {'status':'UPDATED','robot':snap,'live_execution':live_twin.snapshot()}

@router.post('/admin/robot/tasks/{task_id}/override-target')
def admin_override_target(task_id:str,payload:TaskTargetOverride,db:Session=Depends(get_db)):
    task=db.get(RobotTask,task_id)
    if not task: raise HTTPException(404,'task not found')
    if task.status!=RobotTaskStatus.QUEUED.value: raise HTTPException(409,'only queued tasks can be overridden')
    if task.type not in {'RETURN_BOX','STORE_BOX','RECOVERY'}:
        raise HTTPException(409,'target override is restricted to return/store/manual navigation tasks')
    target=get_slot_by_code(db,payload.slot_code)
    if not target: raise HTTPException(404,'target slot not found')
    if not target.enabled or target.status in {'BLOCKED','MAINTENANCE','DISABLED'}:
        raise HTTPException(409,'target location is unavailable')
    if task.type in {'RETURN_BOX','STORE_BOX'} and target.box_id is not None:
        raise HTTPException(409,'target storage location is occupied')
    source=get_slot_by_code(db,task.source_location) if task.source_location else None
    old=get_slot_by_code(db,task.target_location) if task.target_location else None
    box=db.get(Box,task.box_id) if task.box_id else None
    if task.type in {'RETURN_BOX','STORE_BOX'}:
        if old and old.id!=target.id and old.box_id is None and old.status in {'RESERVED','RESERVED_FOR_RETURN'}:
            old.status='FREE'
        target.status='RESERVED'
        if box: box.reserved_return_slot_id=target.id
    task.target_location=target.code
    task.planned_path=semantic_path(source,target,task.type) if source else manual_route_from_robot(target,robot_runtime.x,robot_runtime.z)
    emit(db,'ADMIN_TARGET_OVERRIDE','robot_task',task.id,{'old_target':old.code if old else None,'new_target':target.code})
    db.commit(); db.refresh(task)
    return {'status':'UPDATED','task':as_dict(task),'decision':decision_for_task(db,task)}

@router.websocket('/ws')
async def websocket_endpoint(ws:WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
