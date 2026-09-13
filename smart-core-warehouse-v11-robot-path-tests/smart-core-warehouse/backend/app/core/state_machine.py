from .enums import BoxStatus

ALLOWED = {
    BoxStatus.REGISTERING: {BoxStatus.DRYING, BoxStatus.READY, BoxStatus.QUARANTINED, BoxStatus.FAULTED},
    BoxStatus.DRYING: {BoxStatus.READY, BoxStatus.QUARANTINED, BoxStatus.FAULTED},
    BoxStatus.READY: {BoxStatus.RESERVED, BoxStatus.QUARANTINED, BoxStatus.FAULTED},
    BoxStatus.STORED: {BoxStatus.RESERVED, BoxStatus.READY, BoxStatus.QUARANTINED, BoxStatus.FAULTED},
    BoxStatus.RESERVED: {BoxStatus.RETRIEVAL_PLANNED, BoxStatus.READY, BoxStatus.FAULTED},
    BoxStatus.RETRIEVAL_PLANNED: {BoxStatus.IN_TRANSIT, BoxStatus.FAULTED},
    BoxStatus.IN_TRANSIT: {BoxStatus.AT_PICKING, BoxStatus.RETURNING, BoxStatus.FAULTED},
    BoxStatus.AT_PICKING: {BoxStatus.RETURN_PLANNED, BoxStatus.EMPTY, BoxStatus.FAULTED},
    BoxStatus.RETURN_PLANNED: {BoxStatus.RETURNING, BoxStatus.FAULTED},
    BoxStatus.RETURNING: {BoxStatus.READY, BoxStatus.STORED, BoxStatus.FAULTED},
    BoxStatus.QUARANTINED: {BoxStatus.DRYING, BoxStatus.READY, BoxStatus.EMPTY, BoxStatus.FAULTED},
    BoxStatus.FAULTED: {BoxStatus.READY, BoxStatus.STORED, BoxStatus.QUARANTINED},
    BoxStatus.EMPTY: set(),
}


def transition(current: str, target: str) -> str:
    c, t = BoxStatus(current), BoxStatus(target)
    if t not in ALLOWED.get(c, set()):
        raise ValueError(f'illegal box transition {c} -> {t}')
    return t.value
