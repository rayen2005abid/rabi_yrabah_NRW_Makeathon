from __future__ import annotations

from math import sqrt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import load_yaml
from app.core.enums import SlotType, SlotStatus
from app.core.models import Slot, Box


def _geometry(cfg: dict) -> dict:
    """Normalize warehouse geometry while remaining backward compatible.

    Current physical demo layout:
      - 4 independent rack modules
      - each rack = 8 columns x 8 levels
      - racks 1-2 on aisle side A
      - racks 3-4 on aisle side B
      - one X/Z crane in the central aisle, with signed Y fork insertion

    Older config keys (rack_faces / columns_per_face / levels_per_face) are
    still accepted so geometry remains configuration-driven rather than hard-coded.
    """
    rack_count = int(cfg.get('rack_count', cfg.get('rack_faces', 2)))
    cols = int(cfg.get('columns_per_rack', cfg.get('columns_per_face', 13)))
    levels = int(cfg.get('levels_per_rack', cfg.get('levels_per_face', 18)))
    racks_per_side = max(1, int(cfg.get('racks_per_side', (rack_count + 1) // 2)))
    gap = float(cfg.get('rack_gap_m', 0.25))
    fork_depth = float(cfg.get('fork_insertion_depth_m', cfg.get('spacing_m', {}).get('y', 0.55)))
    return {
        'rack_count': rack_count,
        'columns': cols,
        'levels': levels,
        'racks_per_side': racks_per_side,
        'rack_gap_m': gap,
        'fork_depth_m': fork_depth,
    }


def generate_slots(db: Session, force: bool = False) -> int:
    if not force and db.scalar(select(Slot.id).limit(1)):
        return 0
    if force:
        db.query(Slot).delete()

    cfg = load_yaml('warehouse.yaml')['warehouse']
    geo = _geometry(cfg)
    spacing = cfg.get('spacing_m', {'x': 0.34, 'z': 0.24})
    dims = cfg.get(
        'cell_effective_dimensions_m',
        {'width': 0.34, 'depth': 0.55, 'height': 0.24},
    )
    sx = float(spacing.get('x', 0.34))
    sz = float(spacing.get('z', 0.24))
    rack_pitch_x = geo['columns'] * sx + geo['rack_gap_m']

    created = 0
    for rack in range(1, geo['rack_count'] + 1):
        # Rack modules are paired on opposite sides of the same robot aisle.
        # R1/R3 share X segment 1; R2/R4 share X segment 2.
        side_index = (rack - 1) // geo['racks_per_side']
        module_index = (rack - 1) % geo['racks_per_side']
        side_name = 'A' if side_index % 2 == 0 else 'B'
        fork_y = geo['fork_depth_m'] if side_name == 'A' else -geo['fork_depth_m']
        x_offset = module_index * rack_pitch_x

        for col in range(1, geo['columns'] + 1):
            for level in range(1, geo['levels'] + 1):
                x = x_offset + (col - 1) * sx
                z = (level - 1) * sz
                y = fork_y
                code = f'R{rack}-C{col:02d}-L{level:02d}'
                travel = sqrt(x * x + z * z + y * y)
                db.add(
                    Slot(
                        code=code,
                        rack_face=rack,  # legacy DB column; semantically this is rack_number now
                        column=col,
                        level=level,
                        x_coordinate=x,
                        y_coordinate=y,
                        z_coordinate=z,
                        type=SlotType.STORAGE.value,
                        status=SlotStatus.FREE.value,
                        accessibility_score=max(0.1, 1.0 / (1.0 + travel)),
                        travel_cost=travel,
                        enabled=True,
                        metadata_json={
                            'reachable': True,
                            'capacity_boxes': 1,
                            'dimensions_m': dims,
                            'rack_number': rack,
                            'rack_side': side_name,
                            'rack_module_index': module_index + 1,
                            'x_offset_m': x_offset,
                        },
                    )
                )
                created += 1

    # Transfer zone is located before the first rack module on the same X rail.
    special = []
    for idx in range(int(cfg.get('buffers', {}).get('count', 3))):
        special.append((f'BUFFER-{idx + 1}', SlotType.BUFFER.value, -0.65 - idx * 0.22, 0.0, 0.30))
    special.extend(
        [
            ('ENTRY', SlotType.ENTRY_PICKING.value, -0.85, 0.0, 0.0),
            ('PICKING', SlotType.ENTRY_PICKING.value, -1.10, 0.0, 0.0),
            ('QUARANTINE', SlotType.QUARANTINE.value, -1.35, 0.0, 0.0),
        ]
    )
    for code, typ, x, y, z in special:
        db.add(
            Slot(
                code=code,
                x_coordinate=x,
                y_coordinate=y,
                z_coordinate=z,
                type=typ,
                status=SlotStatus.FREE.value,
                accessibility_score=1.0,
                travel_cost=abs(x),
                enabled=True,
                metadata_json={'reachable': True, 'transfer_zone': True},
            )
        )
        created += 1

    db.commit()
    return created


def list_slots(db: Session):
    return list(
        db.scalars(
            select(Slot).order_by(
                Slot.rack_face.nulls_last(),
                Slot.column.nulls_last(),
                Slot.level.nulls_last(),
                Slot.code,
            )
        ).all()
    )


def get_slot_by_code(db: Session, code: str):
    return db.scalar(select(Slot).where(Slot.code == code))


def free_storage_slots(db: Session):
    return list(
        db.scalars(
            select(Slot).where(
                Slot.type == SlotType.STORAGE.value,
                Slot.status == SlotStatus.FREE.value,
                Slot.enabled.is_(True),
                Slot.box_id.is_(None),
            )
        ).all()
    )


def occupy_slot(db: Session, slot: Slot, box: Box):
    if not slot.enabled or slot.status != SlotStatus.FREE.value or slot.box_id is not None:
        raise ValueError(f'slot {slot.code} is not free')
    slot.status = SlotStatus.OCCUPIED.value
    slot.box_id = box.id
    box.current_slot_id = slot.id


def release_slot(db: Session, slot: Slot):
    slot.box_id = None
    if slot.enabled:
        slot.status = SlotStatus.FREE.value
    else:
        slot.status = SlotStatus.DISABLED.value
