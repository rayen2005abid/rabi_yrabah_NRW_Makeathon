from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

BBox = tuple[int, int, int, int]


@dataclass
class PieceDetection:
    present: bool
    stable: bool
    state: str
    bbox: BBox | None
    presence_score: float
    foreground_ratio: float
    mask: np.ndarray | None = None


def center_zone(frame_shape: tuple[int, ...], width_fraction: float, height_fraction: float) -> BBox:
    h, w = frame_shape[:2]
    zw = max(20, min(w, int(w * width_fraction)))
    zh = max(20, min(h, int(h * height_fraction)))
    x = (w - zw) // 2
    y = (h - zh) // 2
    return x, y, zw, zh


def expand_bbox(bbox: BBox, frame_shape: tuple[int, ...], margin: float) -> BBox:
    x, y, w, h = bbox
    fh, fw = frame_shape[:2]
    px = int(w * margin)
    py = int(h * margin)
    x1 = max(0, x - px)
    y1 = max(0, y - py)
    x2 = min(fw, x + w + px)
    y2 = min(fh, y + h + py)
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _ema_bbox(previous: BBox | None, current: BBox, alpha: float) -> BBox:
    if previous is None:
        return current
    a = min(1.0, max(0.0, float(alpha)))
    return tuple(int(round((1.0 - a) * p + a * c)) for p, c in zip(previous, current))  # type: ignore[return-value]


class MultiFrameBackground:
    """Build a robust empty-station background from several frames.

    A single background frame is very sensitive to webcam noise and auto exposure.
    Using a median of several frames makes the piece detector substantially more
    stable in a fixed industrial camera setup.
    """

    def __init__(self, frame_count: int = 25, blur_kernel: int = 5) -> None:
        self.frame_count = max(3, int(frame_count))
        self.blur_kernel = max(3, int(blur_kernel) | 1)
        self._frames: list[np.ndarray] = []
        self.background_lab: np.ndarray | None = None

    @property
    def calibrated(self) -> bool:
        return self.background_lab is not None

    @property
    def collecting(self) -> bool:
        return 0 < len(self._frames) < self.frame_count

    @property
    def progress(self) -> tuple[int, int]:
        return len(self._frames), self.frame_count

    def start(self) -> None:
        self._frames = []
        self.background_lab = None

    def clear(self) -> None:
        self._frames = []
        self.background_lab = None

    def _prepare(self, frame_bgr: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(frame_bgr, (self.blur_kernel, self.blur_kernel), 0)
        return cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB)

    def add_frame(self, frame_bgr: np.ndarray) -> bool:
        if self.background_lab is not None:
            return True
        self._frames.append(self._prepare(frame_bgr))
        if len(self._frames) >= self.frame_count:
            stack = np.stack(self._frames, axis=0)
            self.background_lab = np.median(stack, axis=0).astype(np.uint8)
            self._frames = []
            return True
        return False

    def adapt(self, frame_bgr: np.ndarray, rate: float) -> None:
        if self.background_lab is None or rate <= 0:
            return
        current = self._prepare(frame_bgr).astype(np.float32)
        background = self.background_lab.astype(np.float32)
        blended = cv2.addWeighted(current, float(rate), background, 1.0 - float(rate), 0.0)
        self.background_lab = blended.astype(np.uint8)


class PiecePresenceDetector:
    """Stable piece/no-piece detector for a fixed PC camera.

    Detection combines multi-frame empty-background calibration, LAB color change,
    morphology, connected-component filtering, a central detection zone and temporal
    hysteresis. The classifier should run only when ``stable`` and ``present`` are
    both True.
    """

    def __init__(
        self,
        calibration_frames: int = 25,
        detection_zone_width: float = 0.90,
        detection_zone_height: float = 0.90,
        diff_threshold: int = 20,
        min_foreground_ratio: float = 0.010,
        min_component_area_ratio: float = 0.008,
        max_component_area_ratio: float = 0.80,
        bbox_margin: float = 0.10,
        blur_kernel: int = 5,
        morph_kernel: int = 5,
        enter_frames: int = 3,
        exit_frames: int = 5,
        bbox_smoothing: float = 0.35,
        min_presence_score: float = 0.18,
        adaptive_background_rate: float = 0.003,
    ) -> None:
        self.background = MultiFrameBackground(calibration_frames, blur_kernel)
        self.detection_zone_width = float(detection_zone_width)
        self.detection_zone_height = float(detection_zone_height)
        self.diff_threshold = int(diff_threshold)
        self.min_foreground_ratio = float(min_foreground_ratio)
        self.min_component_area_ratio = float(min_component_area_ratio)
        self.max_component_area_ratio = float(max_component_area_ratio)
        self.bbox_margin = float(bbox_margin)
        self.morph_kernel = max(3, int(morph_kernel) | 1)
        self.enter_frames = max(1, int(enter_frames))
        self.exit_frames = max(1, int(exit_frames))
        self.bbox_smoothing = float(bbox_smoothing)
        self.min_presence_score = float(min_presence_score)
        self.adaptive_background_rate = float(adaptive_background_rate)
        self._positive_streak = 0
        self._negative_streak = 0
        self._stable_present = False
        self._bbox: BBox | None = None

    @property
    def calibrated(self) -> bool:
        return self.background.calibrated

    @property
    def collecting_background(self) -> bool:
        return self.background.collecting

    @property
    def calibration_progress(self) -> tuple[int, int]:
        return self.background.progress

    def start_calibration(self) -> None:
        self.background.start()
        self._reset_state()

    def clear(self) -> None:
        self.background.clear()
        self._reset_state()

    def _reset_state(self) -> None:
        self._positive_streak = 0
        self._negative_streak = 0
        self._stable_present = False
        self._bbox = None

    def add_calibration_frame(self, frame_bgr: np.ndarray) -> bool:
        return self.background.add_frame(frame_bgr)

    def _raw_detection(self, frame_bgr: np.ndarray) -> tuple[bool, BBox | None, float, float, np.ndarray | None]:
        background = self.background.background_lab
        if background is None:
            return False, None, 0.0, 0.0, None

        prepared = self.background._prepare(frame_bgr)
        if prepared.shape != background.shape:
            return False, None, 0.0, 0.0, None

        x0, y0, zw, zh = center_zone(
            frame_bgr.shape,
            self.detection_zone_width,
            self.detection_zone_height,
        )
        current_zone = prepared[y0 : y0 + zh, x0 : x0 + zw]
        background_zone = background[y0 : y0 + zh, x0 : x0 + zw]
        diff = cv2.absdiff(current_zone, background_zone)

        # LAB maximum-channel difference catches both illumination and color changes.
        score = diff.max(axis=2)
        mask = np.where(score >= self.diff_threshold, 255, 0).astype(np.uint8)
        kernel = np.ones((self.morph_kernel, self.morph_kernel), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        foreground_ratio = float(np.count_nonzero(mask) / max(1, mask.size))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False, None, 0.0, foreground_ratio, mask

        zone_area = float(zw * zh)
        candidates: list[tuple[float, BBox]] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            area_ratio = area / max(1.0, zone_area)
            if not (self.min_component_area_ratio <= area_ratio <= self.max_component_area_ratio):
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 20 or h < 20:
                continue
            aspect = max(w / max(h, 1), h / max(w, 1))
            if aspect > 7.0:
                continue
            global_bbox = (x + x0, y + y0, w, h)
            candidates.append((area_ratio, global_bbox))

        if not candidates:
            return False, None, 0.0, foreground_ratio, mask

        component_ratio, bbox = max(candidates, key=lambda item: item[0])
        bbox = expand_bbox(bbox, frame_bgr.shape, self.bbox_margin)

        # Blend component size and total changed pixels into a human-readable score.
        component_term = min(1.0, component_ratio / max(self.min_component_area_ratio * 4.0, 1e-6))
        foreground_term = min(1.0, foreground_ratio / max(self.min_foreground_ratio * 4.0, 1e-6))
        presence_score = 0.65 * component_term + 0.35 * foreground_term
        raw_present = foreground_ratio >= self.min_foreground_ratio and presence_score >= self.min_presence_score
        return raw_present, bbox, float(presence_score), foreground_ratio, mask

    def update(self, frame_bgr: np.ndarray) -> PieceDetection:
        if not self.calibrated:
            state = "CALIBRATING" if self.collecting_background else "NOT_CALIBRATED"
            return PieceDetection(False, False, state, None, 0.0, 0.0, None)

        raw_present, bbox, score, foreground_ratio, mask = self._raw_detection(frame_bgr)
        if raw_present and bbox is not None:
            self._positive_streak += 1
            self._negative_streak = 0
            self._bbox = _ema_bbox(self._bbox, bbox, self.bbox_smoothing)
            if self._positive_streak >= self.enter_frames:
                self._stable_present = True
        else:
            self._negative_streak += 1
            self._positive_streak = 0
            if self._negative_streak >= self.exit_frames:
                self._stable_present = False
                self._bbox = None
            if not self._stable_present and score < self.min_presence_score * 0.5:
                self.background.adapt(frame_bgr, self.adaptive_background_rate)

        if self._stable_present:
            state = "PIECE_PRESENT"
        elif raw_present:
            state = "PIECE_CANDIDATE"
        else:
            state = "EMPTY"

        return PieceDetection(
            present=self._stable_present,
            stable=self._stable_present,
            state=state,
            bbox=self._bbox if self._stable_present else bbox,
            presence_score=score,
            foreground_ratio=foreground_ratio,
            mask=mask,
        )
