from __future__ import annotations

from dataclasses import dataclass, asdict, field
from math import hypot
from time import monotonic

from app.core.config import load_yaml
from app.robot.runtime import robot_runtime
from app.intelligence.service import passage_route


@dataclass
class LiveTwinExecution:
    """Visual/kinematic execution model for the warehouse Digital Twin.

    The simulation deliberately separates two coordinate systems:

    * floor_x/floor_y -> top-down movement through rack aisles, the main spine,
      and the transfer lane.  This is what the operator sees on the warehouse
      floor map.
    * robot_runtime x/z/y -> stacker/rack motion (column, lift height, fork
      insertion).  This is what the rack close-up and telemetry panels show.

    Inventory is mutated only after the final visual VERIFY phase when the
    embedded mock adapter acknowledges the task.
    """

    active: bool = False
    task_id: str | None = None
    source_code: str | None = None
    target_code: str | None = None
    source_is_storage: bool = False
    target_is_storage: bool = False

    source_x: float = 0.0
    source_y: float = 0.0
    source_z: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    target_z: float = 0.0
    start_x: float = 0.0
    start_y: float = 0.0
    start_z: float = 0.0

    # Top-down passage position. Coordinates are normalized to the 6m x 6m map.
    floor_x: float = 0.08
    floor_y: float = 0.08
    floor_label: str = 'Transfer zone'
    journey_stage: str = 'IDLE'
    route_progress: float = 0.0
    approach_route: list[dict] = field(default_factory=list)
    transfer_route: list[dict] = field(default_factory=list)

    phase: str = 'IDLE'
    phase_progress: float = 0.0
    progress: float = 0.0
    carrying_box: bool = False

    estimated_duration_s: float = 0.0
    simulated_elapsed_s: float = 0.0
    playback_speed: float = 2.0
    path_distance_m: float = 0.0
    traveled_distance_m: float = 0.0
    segments: list[dict] = field(default_factory=list)

    _last_tick_monotonic: float = 0.0

    def _cfg(self) -> dict:
        return load_yaml('robot.yaml').get('robot', {})

    @staticmethod
    def _lerp(a: float, b: float, p: float) -> float:
        return a + (b - a) * max(0.0, min(1.0, p))

    @staticmethod
    def _route_length(nodes: list[dict]) -> float:
        return sum(
            hypot(float(b['x']) - float(a['x']), float(b['y']) - float(a['y']))
            for a, b in zip(nodes, nodes[1:])
        )

    @classmethod
    def _route_point(cls, nodes: list[dict], p: float) -> tuple[float, float, str]:
        if not nodes:
            return 0.08, 0.08, 'Transfer zone'
        if len(nodes) == 1:
            n = nodes[0]
            return float(n['x']), float(n['y']), str(n.get('label') or n.get('node_id') or 'Route')
        p = max(0.0, min(1.0, p))
        lengths = [
            hypot(float(b['x']) - float(a['x']), float(b['y']) - float(a['y']))
            for a, b in zip(nodes, nodes[1:])
        ]
        total = sum(lengths)
        if total <= 1e-9:
            n = nodes[-1]
            return float(n['x']), float(n['y']), str(n.get('label') or 'Route')
        target = total * p
        cursor = 0.0
        for i, seg_len in enumerate(lengths):
            if cursor + seg_len >= target or i == len(lengths) - 1:
                local = 1.0 if seg_len <= 1e-9 else (target - cursor) / seg_len
                a, b = nodes[i], nodes[i + 1]
                return (
                    cls._lerp(float(a['x']), float(b['x']), local),
                    cls._lerp(float(a['y']), float(b['y']), local),
                    str(b.get('label') or b.get('node_id') or 'Route'),
                )
            cursor += seg_len
        n = nodes[-1]
        return float(n['x']), float(n['y']), str(n.get('label') or 'Route')

    def _build_segments(
        self,
        x_speed: float,
        z_speed: float,
        y_speed: float,
        load_s: float,
        unload_s: float,
    ) -> list[dict]:
        # Passage graph is normalized to a conceptual 6m x 6m floor plan.
        floor_speed = max(x_speed, 0.20)
        approach_m = self._route_length(self.approach_route) * 6.0
        transfer_m = self._route_length(self.transfer_route) * 6.0
        approach_s = approach_m / floor_speed
        transfer_s = transfer_m / floor_speed

        src_lift_s = abs(self.source_z) / max(z_speed, 0.01) if self.source_is_storage else 0.0
        tgt_lift_s = abs(self.target_z) / max(z_speed, 0.01) if self.target_is_storage else 0.0
        src_fork_s = abs(self.source_y) / max(y_speed, 0.01)
        tgt_fork_s = abs(self.target_y) / max(y_speed, 0.01)

        source_stage = 'SOURCE_RACK' if self.source_is_storage else 'SOURCE_STATION'
        target_stage = 'TARGET_RACK' if self.target_is_storage else 'TARGET_STATION'
        return [
            {'phase': 'SAFETY_CHECK', 'duration_s': 0.25, 'stage': 'PREPARE'},
            {'phase': 'TRAVEL_TO_SOURCE_PASSAGE', 'duration_s': approach_s, 'stage': 'PASSAGE_TO_SOURCE'},
            {'phase': 'ENTER_SOURCE_RACK', 'duration_s': 0.28 if self.source_is_storage else 0.08, 'stage': source_stage},
            {'phase': 'LIFT_TO_SOURCE_LEVEL', 'duration_s': src_lift_s, 'stage': source_stage},
            {'phase': 'EXTEND_FORK_SOURCE', 'duration_s': src_fork_s, 'stage': source_stage},
            {'phase': 'LOAD_BOX', 'duration_s': load_s, 'stage': source_stage},
            {'phase': 'RETRACT_WITH_BOX', 'duration_s': src_fork_s, 'stage': source_stage},
            {'phase': 'LOWER_FROM_SOURCE_LEVEL', 'duration_s': src_lift_s, 'stage': source_stage},
            {'phase': 'EXIT_SOURCE_RACK', 'duration_s': 0.28 if self.source_is_storage else 0.08, 'stage': 'PASSAGE'},
            {'phase': 'TRAVEL_TRANSFER_LANE', 'duration_s': transfer_s, 'stage': 'TRANSFER_LANE'},
            {'phase': 'ENTER_TARGET_RACK', 'duration_s': 0.28 if self.target_is_storage else 0.08, 'stage': target_stage},
            {'phase': 'LIFT_TO_TARGET_LEVEL', 'duration_s': tgt_lift_s, 'stage': target_stage},
            {'phase': 'EXTEND_FORK_TARGET', 'duration_s': tgt_fork_s, 'stage': target_stage},
            {'phase': 'UNLOAD_BOX', 'duration_s': unload_s, 'stage': target_stage},
            {'phase': 'RETRACT_FORK_TARGET', 'duration_s': tgt_fork_s, 'stage': target_stage},
            {'phase': 'LOWER_FROM_TARGET_LEVEL', 'duration_s': tgt_lift_s, 'stage': target_stage},
            {'phase': 'VERIFY_TARGET', 'duration_s': 0.30, 'stage': 'VERIFY'},
        ]

    def start(self, task_id: str, source, target) -> dict:
        if self.active:
            raise ValueError('digital twin execution already running')

        cfg = self._cfg()
        x_speed = max(float(cfg.get('x_speed_mps', 1.2)), 0.01)
        z_speed = max(float(cfg.get('z_speed_mps', 0.8)), 0.01)
        y_speed = max(float(cfg.get('y_speed_mps', 0.25)), 0.01)
        load_s = max(float(cfg.get('load_time_s', 1.2)), 0.0)
        unload_s = max(float(cfg.get('unload_time_s', 1.2)), 0.0)
        self.playback_speed = max(float(cfg.get('mock_realtime_speed_multiplier', 2.0)), 0.1)

        self.active = True
        self.task_id = task_id
        self.source_code = source.code if source else None
        self.target_code = target.code if target else None
        self.source_is_storage = bool(source and source.type == 'STORAGE')
        self.target_is_storage = bool(target and target.type == 'STORAGE')

        self.source_x = float(source.x_coordinate if source else robot_runtime.x)
        self.source_y = float(source.y_coordinate if source else 0.0)
        self.source_z = float(source.z_coordinate if source else robot_runtime.z)
        self.target_x = float(target.x_coordinate if target else self.source_x)
        self.target_y = float(target.y_coordinate if target else 0.0)
        self.target_z = float(target.z_coordinate if target else self.source_z)
        self.start_x = float(robot_runtime.x)
        self.start_y = float(robot_runtime.y)
        self.start_z = float(robot_runtime.z)

        self.approach_route = passage_route(None, source).get('nodes', [])
        self.transfer_route = passage_route(source, target).get('nodes', [])
        self.floor_x, self.floor_y, self.floor_label = self._route_point(self.approach_route, 0.0)
        self.route_progress = 0.0
        self.journey_stage = 'PREPARE'

        self.segments = self._build_segments(x_speed, z_speed, y_speed, load_s, unload_s)
        self.estimated_duration_s = sum(max(0.0, float(s['duration_s'])) for s in self.segments)
        self.simulated_elapsed_s = 0.0
        self._last_tick_monotonic = monotonic()
        self.phase = 'SAFETY_CHECK'
        self.phase_progress = 0.0
        self.progress = 0.0
        self.carrying_box = False
        floor_m = (self._route_length(self.approach_route) + self._route_length(self.transfer_route)) * 6.0
        vertical_m = (abs(self.source_z) * 2 if self.source_is_storage else 0.0) + (abs(self.target_z) * 2 if self.target_is_storage else 0.0)
        fork_m = abs(self.source_y) * 2 + abs(self.target_y) * 2
        self.path_distance_m = floor_m + vertical_m + fork_m
        self.traveled_distance_m = 0.0

        robot_runtime.current_task_id = task_id
        robot_runtime.mode = 'RUNNING'
        robot_runtime.carrying_box = False
        return self.snapshot()

    def set_speed(self, multiplier: float) -> dict:
        if multiplier < 0.5 or multiplier > 20.0:
            raise ValueError('speed must be between 0.5 and 20')
        if self.active:
            self._advance_clock()
        self.playback_speed = float(multiplier)
        return self.snapshot()

    def _advance_clock(self) -> None:
        now = monotonic()
        if not self._last_tick_monotonic:
            self._last_tick_monotonic = now
            return
        wall_delta = max(0.0, now - self._last_tick_monotonic)
        self._last_tick_monotonic = now
        self.simulated_elapsed_s = min(
            self.estimated_duration_s,
            self.simulated_elapsed_s + wall_delta * self.playback_speed,
        )

    def _set_floor_from_route(self, nodes: list[dict], p: float) -> None:
        self.floor_x, self.floor_y, self.floor_label = self._route_point(nodes, p)
        self.route_progress = max(0.0, min(1.0, p))

    def _apply_phase(self, phase: str, p: float) -> None:
        # Top-down floor movement and rack motion are updated together so the UI
        # can switch smoothly between the floor map and the rack close-up.
        if phase == 'SAFETY_CHECK':
            self._set_floor_from_route(self.approach_route, 0.0)
            robot_runtime.y = 0.0
            robot_runtime.z = 0.0
            self.carrying_box = False

        elif phase == 'TRAVEL_TO_SOURCE_PASSAGE':
            self._set_floor_from_route(self.approach_route, p)
            robot_runtime.x = self._lerp(self.start_x, self.source_x, p)
            robot_runtime.z = 0.0
            robot_runtime.y = 0.0
            self.carrying_box = False

        elif phase == 'ENTER_SOURCE_RACK':
            self._set_floor_from_route(self.approach_route, 1.0)
            robot_runtime.x = self.source_x
            robot_runtime.z = 0.0
            robot_runtime.y = 0.0
            self.carrying_box = False

        elif phase == 'LIFT_TO_SOURCE_LEVEL':
            self._set_floor_from_route(self.approach_route, 1.0)
            robot_runtime.x = self.source_x
            robot_runtime.z = self._lerp(0.0, self.source_z, p) if self.source_is_storage else self.source_z
            robot_runtime.y = 0.0
            self.carrying_box = False

        elif phase == 'EXTEND_FORK_SOURCE':
            robot_runtime.x, robot_runtime.z = self.source_x, self.source_z
            robot_runtime.y = self._lerp(0.0, self.source_y, p)
            self.carrying_box = False

        elif phase == 'LOAD_BOX':
            robot_runtime.x, robot_runtime.y, robot_runtime.z = self.source_x, self.source_y, self.source_z
            self.carrying_box = p >= 0.50

        elif phase == 'RETRACT_WITH_BOX':
            robot_runtime.x, robot_runtime.z = self.source_x, self.source_z
            robot_runtime.y = self._lerp(self.source_y, 0.0, p)
            self.carrying_box = True

        elif phase == 'LOWER_FROM_SOURCE_LEVEL':
            robot_runtime.x = self.source_x
            robot_runtime.z = self._lerp(self.source_z, 0.0, p) if self.source_is_storage else self.source_z
            robot_runtime.y = 0.0
            self.carrying_box = True

        elif phase == 'EXIT_SOURCE_RACK':
            self._set_floor_from_route(self.transfer_route, 0.0)
            robot_runtime.x, robot_runtime.z, robot_runtime.y = self.source_x, 0.0, 0.0
            self.carrying_box = True

        elif phase == 'TRAVEL_TRANSFER_LANE':
            self._set_floor_from_route(self.transfer_route, p)
            robot_runtime.x = self._lerp(self.source_x, self.target_x, p)
            robot_runtime.z = 0.0
            robot_runtime.y = 0.0
            self.carrying_box = True

        elif phase == 'ENTER_TARGET_RACK':
            self._set_floor_from_route(self.transfer_route, 1.0)
            robot_runtime.x, robot_runtime.z, robot_runtime.y = self.target_x, 0.0, 0.0
            self.carrying_box = True

        elif phase == 'LIFT_TO_TARGET_LEVEL':
            self._set_floor_from_route(self.transfer_route, 1.0)
            robot_runtime.x = self.target_x
            robot_runtime.z = self._lerp(0.0, self.target_z, p) if self.target_is_storage else self.target_z
            robot_runtime.y = 0.0
            self.carrying_box = True

        elif phase == 'EXTEND_FORK_TARGET':
            robot_runtime.x, robot_runtime.z = self.target_x, self.target_z
            robot_runtime.y = self._lerp(0.0, self.target_y, p)
            self.carrying_box = True

        elif phase == 'UNLOAD_BOX':
            robot_runtime.x, robot_runtime.y, robot_runtime.z = self.target_x, self.target_y, self.target_z
            self.carrying_box = p < 0.50

        elif phase == 'RETRACT_FORK_TARGET':
            robot_runtime.x, robot_runtime.z = self.target_x, self.target_z
            robot_runtime.y = self._lerp(self.target_y, 0.0, p)
            self.carrying_box = False

        elif phase == 'LOWER_FROM_TARGET_LEVEL':
            robot_runtime.x = self.target_x
            robot_runtime.z = self._lerp(self.target_z, 0.0, p) if self.target_is_storage else self.target_z
            robot_runtime.y = 0.0
            self.carrying_box = False

        elif phase == 'VERIFY_TARGET':
            self._set_floor_from_route(self.transfer_route, 1.0)
            robot_runtime.x, robot_runtime.y, robot_runtime.z = self.target_x, 0.0, 0.0 if self.target_is_storage else self.target_z
            self.carrying_box = False

        robot_runtime.carrying_box = self.carrying_box

    def tick(self) -> dict:
        if not self.active:
            return self.snapshot()

        self._advance_clock()
        total = max(self.estimated_duration_s, 0.001)
        self.progress = min(1.0, self.simulated_elapsed_s / total)

        cursor = 0.0
        active_segment = self.segments[-1] if self.segments else {'phase': 'VERIFY_TARGET', 'duration_s': 0.0, 'stage': 'VERIFY'}
        local = 1.0
        for seg in self.segments:
            duration = max(0.0, float(seg['duration_s']))
            end = cursor + duration
            if self.simulated_elapsed_s <= end or seg is self.segments[-1]:
                active_segment = seg
                local = 1.0 if duration <= 1e-9 else (self.simulated_elapsed_s - cursor) / duration
                local = max(0.0, min(1.0, local))
                break
            cursor = end

        self.phase = str(active_segment['phase'])
        self.journey_stage = str(active_segment.get('stage') or self.phase)
        self.phase_progress = local
        self._apply_phase(self.phase, local)
        self.traveled_distance_m = self.path_distance_m * self.progress

        if self.progress >= 1.0:
            self.phase = 'VERIFY_TARGET'
            self.journey_stage = 'VERIFY'
            self.phase_progress = 1.0
            self._apply_phase(self.phase, 1.0)

        return self.snapshot()

    def finish_visual(self) -> None:
        self.active = False
        self.phase = 'IDLE'
        self.journey_stage = 'IDLE'
        self.phase_progress = 0.0
        self.progress = 1.0
        self.carrying_box = False
        self.simulated_elapsed_s = self.estimated_duration_s
        robot_runtime.carrying_box = False

    def cancel(self) -> dict:
        self.active = False
        self.task_id = None
        self.phase = 'IDLE'
        self.journey_stage = 'IDLE'
        self.phase_progress = 0.0
        self.progress = 0.0
        self.carrying_box = False
        self.simulated_elapsed_s = 0.0
        self.segments = []
        self.approach_route = []
        self.transfer_route = []
        self.floor_x = 0.08
        self.floor_y = 0.08
        self.floor_label = 'Transfer zone'
        self.route_progress = 0.0
        robot_runtime.current_task_id = None
        robot_runtime.carrying_box = False
        if not robot_runtime.estop and not robot_runtime.fault:
            robot_runtime.mode = 'IDLE'
        return self.snapshot()

    def snapshot(self) -> dict:
        d = asdict(self)
        d.pop('_last_tick_monotonic', None)
        remaining_sim = max(0.0, self.estimated_duration_s - self.simulated_elapsed_s)
        d['estimated_remaining_s'] = remaining_sim if self.active else 0.0
        d['remaining_s'] = (remaining_sim / max(self.playback_speed, 0.1)) if self.active else 0.0
        d['demo_duration_s'] = self.estimated_duration_s / max(self.playback_speed, 0.1)
        return d


live_twin = LiveTwinExecution()
