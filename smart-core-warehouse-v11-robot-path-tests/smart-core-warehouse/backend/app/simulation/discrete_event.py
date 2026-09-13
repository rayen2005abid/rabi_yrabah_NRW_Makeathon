from __future__ import annotations

from app.core.config import load_yaml


def build_transfer_timeline(transfers: list[dict]) -> tuple[list[dict], str]:
    """Build a sequential one-robot discrete-event timeline.

    Each transfer models the real semantic sequence used by the WCS:
    safe fork -> empty travel -> align -> fork insert -> load -> retract ->
    carrying travel -> align -> unload -> retract -> verify.

    X and Z travel concurrently, therefore MOVE duration is max(tx, tz), not tx+tz.
    """
    cfg = load_yaml('robot.yaml')['robot']
    try:
        import simpy
    except ImportError:
        t = 0.0
        events: list[dict] = []
        for tr in transfers:
            for label, duration in _durations(tr, cfg):
                start = t
                t += duration
                events.append({
                    't_start': round(start, 3),
                    't': round(t, 3),
                    'duration_s': round(duration, 3),
                    'event': label,
                    'box_code': tr['box_code'],
                    'task': tr.get('task', 'TRANSFER'),
                    'source': tr.get('source'),
                    'target': tr.get('target'),
                })
        return events, 'DETERMINISTIC_FALLBACK'

    env = simpy.Environment()
    events: list[dict] = []

    def proc(tr: dict):
        for label, duration in _durations(tr, cfg):
            start = env.now
            yield env.timeout(duration)
            events.append({
                't_start': round(start, 3),
                't': round(env.now, 3),
                'duration_s': round(duration, 3),
                'event': label,
                'box_code': tr['box_code'],
                'task': tr.get('task', 'TRANSFER'),
                'source': tr.get('source'),
                'target': tr.get('target'),
            })

    def sequence():
        for tr in transfers:
            yield env.process(proc(tr))

    env.process(sequence())
    env.run()
    return events, 'SIMPY'


def _durations(tr: dict, cfg: dict) -> list[tuple[str, float]]:
    x_speed = max(float(cfg['x_speed_mps']), 1e-9)
    z_speed = max(float(cfg['z_speed_mps']), 1e-9)
    y_speed = max(float(cfg['y_speed_mps']), 1e-9)
    load_s = max(float(cfg['load_time_s']), 0.0)
    unload_s = max(float(cfg['unload_time_s']), 0.0)

    empty_dx = abs(float(tr.get('empty_dx', 0.0)))
    empty_dz = abs(float(tr.get('empty_dz', 0.0)))
    carry_dx = abs(float(tr.get('carry_dx', 0.0)))
    carry_dz = abs(float(tr.get('carry_dz', 0.0)))
    source_y = abs(float(tr.get('source_y', 0.0)))
    target_y = abs(float(tr.get('target_y', 0.0)))

    return [
        ('SAFETY_CHECK', 0.20),
        ('MOVE_EMPTY_TO_SOURCE', max(empty_dx / x_speed, empty_dz / z_speed)),
        ('ALIGN_SOURCE', 0.18),
        ('EXTEND_FORK_SOURCE', source_y / y_speed),
        ('LOAD_BOX', load_s),
        ('RETRACT_WITH_BOX', source_y / y_speed),
        ('MOVE_CARRYING_TO_TARGET', max(carry_dx / x_speed, carry_dz / z_speed)),
        ('ALIGN_TARGET', 0.18),
        ('EXTEND_FORK_TARGET', target_y / y_speed),
        ('UNLOAD_BOX', unload_s),
        ('RETRACT_FORK_TARGET', target_y / y_speed),
        ('VERIFY_TARGET', 0.25),
    ]
