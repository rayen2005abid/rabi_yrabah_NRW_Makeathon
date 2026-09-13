from __future__ import annotations
from math import sqrt
from app.core.config import load_yaml

def reconcile_position(expected: dict, observed: dict, tolerance: float | None = None) -> dict:
    if tolerance is None:
        tolerance=float(load_yaml('robot.yaml')['robot'].get('position_tolerance_m',0.02))
    dx=float(observed.get('x',0))-float(expected.get('x',0)); dy=float(observed.get('y',0))-float(expected.get('y',0)); dz=float(observed.get('z',0))-float(expected.get('z',0))
    error=sqrt(dx*dx+dy*dy+dz*dz)
    return {'ok':error<=tolerance,'error_m':error,'tolerance_m':tolerance,'reason':None if error<=tolerance else 'POSITION_MISMATCH'}
