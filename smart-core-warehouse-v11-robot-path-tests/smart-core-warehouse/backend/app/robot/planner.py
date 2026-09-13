from __future__ import annotations
from app.core.models import Slot
from app.intelligence.service import passage_route


def semantic_path(source: Slot, target: Slot, operation: str = 'TRANSFER') -> list[dict]:
    route = passage_route(source, target)
    return [
        {'action':'RETRACT_Y','target':0.0,'label':'Retract fork before travel'},
        {
            'action':'NAVIGATE_PASSAGE',
            'label':'Follow intelligent A* passage route',
            'algorithm':route['algorithm'],
            'distance_units':route['distance_units'],
            'route':route['nodes'],
        },
        {'action':'MOVE_XZ','x':source.x_coordinate,'z':source.z_coordinate,'label':f'Align with source {source.code}'},
        {'action':'EXTEND_Y','y':source.y_coordinate,'label':'Extend fork into source rack'},
        {'action':'LOAD','label':'Load box'},
        {'action':'RETRACT_Y','target':0.0,'label':'Retract box into safe passage envelope'},
        {'action':'MOVE_XZ','x':target.x_coordinate,'z':target.z_coordinate,'label':f'Move to target {target.code}'},
        {'action':'EXTEND_Y','y':target.y_coordinate,'label':'Extend fork to target'},
        {'action':'UNLOAD','label':'Unload box'},
        {'action':'RETRACT_Y','target':0.0,'label':'Retract fork and verify target'},
    ]
