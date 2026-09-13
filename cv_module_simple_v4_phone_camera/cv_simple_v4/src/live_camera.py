from __future__ import annotations

import argparse
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image

from src.config import load_config
from src.explainability import draw_salient_regions, green_attention_overlay, salient_regions
from src.inference import ClassProbability, ClassificationResult, CoreClassifier, confidence_status
from src.piece_detection import BBox, PieceDetection, PiecePresenceDetector, center_zone


@dataclass
class LocatedObject:
    bbox: BBox
    method: str
    area_ratio: float | None = None


def _result_to_probability_vector(result: ClassificationResult, class_names: list[str]) -> np.ndarray:
    probabilities = {result.core_type: result.confidence}
    probabilities.update({item.core_type: item.confidence for item in result.alternatives})
    return np.asarray([probabilities.get(name, 0.0) for name in class_names], dtype=np.float64)


def smooth_probability_history(
    history: Iterable[np.ndarray],
    class_names: list[str],
    accept_threshold: float,
    review_threshold: float,
    model_version: str,
    top_k: int = 3,
    minimum_top1_margin: float = 0.0,
) -> ClassificationResult:
    """Average recent probabilities and reject ambiguous top-1/top-2 decisions."""
    items = list(history)
    if not items:
        raise ValueError("At least one probability vector is required")
    probabilities = np.stack(items, axis=0).mean(axis=0)
    total = float(probabilities.sum())
    if total > 0:
        probabilities /= total

    k = max(1, min(int(top_k), len(class_names)))
    ranked = np.argsort(probabilities)[::-1][:k]
    ranking = [
        ClassProbability(class_names[int(index)], float(probabilities[index]))
        for index in ranked
    ]
    best = ranking[0]
    status = confidence_status(best.confidence, accept_threshold, review_threshold)
    if len(ranking) > 1:
        margin = best.confidence - ranking[1].confidence
        if margin < float(minimum_top1_margin):
            status = "MANUAL_REVIEW"
    return ClassificationResult(
        core_type=best.core_type,
        confidence=best.confidence,
        alternatives=ranking[1:],
        status=status,
        model_version=model_version,
    )


def frame_to_pil(frame_bgr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))


def center_bbox(frame_shape: tuple[int, ...], width_fraction: float = 0.65, height_fraction: float = 0.75) -> BBox:
    return center_zone(frame_shape, width_fraction, height_fraction)


def crop_bbox(frame: np.ndarray, bbox: BBox) -> np.ndarray:
    x, y, width, height = bbox
    return frame[y : y + height, x : x + width]


class ForegroundObjectLocator:
    """Compatibility wrapper around the new piece detector for tests/older code."""

    def __init__(
        self,
        threshold: int = 28,
        min_area_ratio: float = 0.025,
        max_area_ratio: float = 0.85,
        margin: float = 0.12,
        blur_kernel: int = 7,
        morph_kernel: int = 7,
    ) -> None:
        self.detector = PiecePresenceDetector(
            calibration_frames=3,
            detection_zone_width=1.0,
            detection_zone_height=1.0,
            diff_threshold=threshold,
            min_foreground_ratio=max(0.001, min_area_ratio / 4.0),
            min_component_area_ratio=min_area_ratio,
            max_component_area_ratio=max_area_ratio,
            bbox_margin=margin,
            blur_kernel=blur_kernel,
            morph_kernel=morph_kernel,
            enter_frames=1,
            exit_frames=1,
            min_presence_score=0.05,
            adaptive_background_rate=0.0,
        )

    @property
    def calibrated(self) -> bool:
        return self.detector.calibrated

    def set_background(self, frame_bgr: np.ndarray) -> None:
        self.detector.start_calibration()
        for _ in range(3):
            self.detector.add_calibration_frame(frame_bgr)

    def clear(self) -> None:
        self.detector.clear()

    def detect(self, frame_bgr: np.ndarray) -> LocatedObject | None:
        detection = self.detector.update(frame_bgr)
        if detection.present and detection.bbox is not None:
            return LocatedObject(detection.bbox, "BACKGROUND", detection.foreground_ratio)
        return None


def _status_color(status: str) -> tuple[int, int, int]:
    if status == "ACCEPTED":
        return (40, 220, 40)
    if status == "LOW_CONFIDENCE":
        return (0, 200, 255)
    return (40, 40, 230)


def _draw_text_box(frame: np.ndarray, lines: list[str], status: str, x: int = 20, y: int = 30) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.62
    thickness = 2
    line_height = 27
    padding = 12
    widths = [cv2.getTextSize(line, font, font_scale, thickness)[0][0] for line in lines]
    panel_width = max(widths, default=260) + 2 * padding
    panel_height = len(lines) * line_height + 2 * padding
    overlay = frame.copy()
    cv2.rectangle(overlay, (x - padding, y - 24), (x - padding + panel_width, y - 24 + panel_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
    color = _status_color(status)
    for index, line in enumerate(lines):
        line_color = color if index < 3 else (230, 230, 230)
        cv2.putText(frame, line, (x, y + index * line_height), font, font_scale, line_color, thickness, cv2.LINE_AA)


def _draw_crop_preview(display: np.ndarray, crop: np.ndarray, width: int = 250, label: str = "MODEL CROP") -> None:
    if crop is None or crop.size == 0:
        return
    h, w = crop.shape[:2]
    scale = width / max(w, 1)
    preview = cv2.resize(crop, (width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    max_h = max(1, display.shape[0] // 3)
    if preview.shape[0] > max_h:
        scale = max_h / preview.shape[0]
        preview = cv2.resize(preview, (max(1, int(preview.shape[1] * scale)), max_h), interpolation=cv2.INTER_AREA)
    ph, pw = preview.shape[:2]
    x1 = max(0, display.shape[1] - pw - 20)
    y1 = 20
    display[y1 : y1 + ph, x1 : x1 + pw] = preview
    green = (40, 235, 40)
    cv2.rectangle(display, (x1, y1), (x1 + pw, y1 + ph), green, 2)
    cv2.putText(display, label, (x1, min(display.shape[0] - 5, y1 + ph + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, green, 2, cv2.LINE_AA)


def _open_camera(camera_index: int) -> cv2.VideoCapture:
    if hasattr(cv2, "CAP_DSHOW"):
        capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if capture.isOpened():
            return capture
        capture.release()
    return cv2.VideoCapture(camera_index)


def _manual_roi(frame: np.ndarray, window_name: str) -> BBox | None:
    bbox = cv2.selectROI(window_name, frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    x, y, width, height = [int(value) for value in bbox]
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _prediction_is_stable(history: deque[str], required: int) -> bool:
    if required <= 1:
        return True
    if len(history) < required:
        return False
    recent = list(history)[-required:]
    return len(set(recent)) == 1


def run_live_camera(
    classifier: CoreClassifier,
    config: dict,
    camera_index: int | None = None,
) -> None:
    camera_cfg = config.get("camera", {})
    piece_cfg = camera_cfg.get("piece_detection", {})
    index = int(camera_cfg.get("index", 0) if camera_index is None else camera_index)
    width = int(camera_cfg.get("width", 1280))
    height = int(camera_cfg.get("height", 720))
    mirror = bool(camera_cfg.get("mirror", True))
    inference_every = max(1, int(camera_cfg.get("inference_every_n_frames", 4)))
    smoothing_window = max(1, int(camera_cfg.get("smoothing_window", 7)))
    top_k = max(1, min(int(camera_cfg.get("top_k", 3)), len(classifier.class_names)))
    min_margin = float(camera_cfg.get("minimum_top1_margin", 0.10))
    stable_prediction_frames = max(1, int(camera_cfg.get("stable_prediction_frames", 3)))
    save_dir = Path(camera_cfg.get("save_dir", "reports/camera_captures"))
    save_dir.mkdir(parents=True, exist_ok=True)

    detector = PiecePresenceDetector(
        calibration_frames=int(piece_cfg.get("calibration_frames", 25)),
        detection_zone_width=float(piece_cfg.get("detection_zone_width", 0.90)),
        detection_zone_height=float(piece_cfg.get("detection_zone_height", 0.90)),
        diff_threshold=int(piece_cfg.get("diff_threshold", 20)),
        min_foreground_ratio=float(piece_cfg.get("min_foreground_ratio", 0.010)),
        min_component_area_ratio=float(piece_cfg.get("min_component_area_ratio", 0.008)),
        max_component_area_ratio=float(piece_cfg.get("max_component_area_ratio", 0.80)),
        bbox_margin=float(piece_cfg.get("bbox_margin", 0.10)),
        blur_kernel=int(piece_cfg.get("blur_kernel", 5)),
        morph_kernel=int(piece_cfg.get("morph_kernel", 5)),
        enter_frames=int(piece_cfg.get("enter_frames", 3)),
        exit_frames=int(piece_cfg.get("exit_frames", 5)),
        bbox_smoothing=float(piece_cfg.get("bbox_smoothing", 0.35)),
        min_presence_score=float(piece_cfg.get("min_presence_score", 0.18)),
        adaptive_background_rate=float(piece_cfg.get("adaptive_background_rate", 0.003)),
    )

    detail_enabled = bool(camera_cfg.get("detail_focus_enabled", True))
    detail_every = max(1, int(camera_cfg.get("detail_every_n_inferences", 3)))
    detail_threshold = float(camera_cfg.get("detail_threshold", 0.60))
    detail_alpha = float(camera_cfg.get("detail_overlay_alpha", 0.40))
    detail_max_regions = max(1, int(camera_cfg.get("detail_max_regions", 3)))

    capture = _open_camera(index)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open camera index {index}. Try --camera-index 1 and check Windows camera permissions.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    probability_history: deque[np.ndarray] = deque(maxlen=smoothing_window)
    prediction_history: deque[str] = deque(maxlen=max(stable_prediction_frames, 1))
    current_result: ClassificationResult | None = None
    current_crop: np.ndarray | None = None
    current_detail: np.ndarray | None = None
    current_regions = []
    manual_bbox: BBox | None = None
    frame_index = 0
    inference_count = 0
    last_inference_ms = 0.0
    window_name = f"Smart Core Warehouse - {classifier.model_version}"

    print("Camera started.")
    print("1) REMOVE the piece from the station.")
    print("2) Press B and keep the station empty while background calibration completes.")
    print("3) Put a piece in view. Classification starts only after stable piece detection.")
    print("Controls: B=calibrate | R=manual ROI | C=clear ROI | X=clear background | D=details | S=save crop | Q=quit")

    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                time.sleep(0.03)
                continue
            if mirror:
                frame = cv2.flip(frame, 1)
            frame_index += 1

            if detector.collecting_background:
                completed = detector.add_calibration_frame(frame)
                detection = PieceDetection(False, False, "CALIBRATING", None, 0.0, 0.0)
                if completed:
                    print("Background calibration complete. Place a piece in the detection zone.")
            elif manual_bbox is not None:
                detection = PieceDetection(True, True, "MANUAL", manual_bbox, 1.0, 1.0)
            else:
                detection = detector.update(frame)

            can_classify = detection.present and detection.stable and detection.bbox is not None
            if can_classify and (current_result is None or frame_index % inference_every == 0):
                crop = crop_bbox(frame, detection.bbox)
                if crop.size > 0:
                    started = time.perf_counter()
                    pil_crop = frame_to_pil(crop)
                    raw_result, _ = classifier.predict_with_diagnostics(pil_crop, top_k=len(classifier.class_names))
                    probability_history.append(_result_to_probability_vector(raw_result, classifier.class_names))
                    current_result = smooth_probability_history(
                        probability_history,
                        classifier.class_names,
                        classifier.accept_threshold,
                        classifier.review_threshold,
                        classifier.model_version,
                        top_k=top_k,
                        minimum_top1_margin=min_margin,
                    )
                    prediction_history.append(current_result.core_type)
                    current_crop = crop.copy()
                    inference_count += 1

                    if detail_enabled and (current_detail is None or inference_count % detail_every == 0):
                        attention, _ = classifier.explain_pil(pil_crop, class_name=current_result.core_type)
                        current_regions = salient_regions(
                            attention,
                            image_width=crop.shape[1],
                            image_height=crop.shape[0],
                            threshold=detail_threshold,
                            max_regions=detail_max_regions,
                        )
                        current_detail = green_attention_overlay(
                            crop,
                            attention,
                            threshold=max(0.0, detail_threshold - 0.07),
                            alpha=detail_alpha,
                        )
                        current_detail = draw_salient_regions(current_detail, current_regions)
                    last_inference_ms = (time.perf_counter() - started) * 1000.0
            elif not can_classify:
                probability_history.clear()
                prediction_history.clear()
                current_result = None
                current_crop = None
                current_detail = None
                current_regions = []

            display = frame.copy()
            green = (40, 235, 40)

            # Show the configured detection zone so the operator knows where piece
            # presence is evaluated.
            zx, zy, zw, zh = center_zone(
                frame.shape,
                float(piece_cfg.get("detection_zone_width", 0.90)),
                float(piece_cfg.get("detection_zone_height", 0.90)),
            )
            cv2.rectangle(display, (zx, zy), (zx + zw, zy + zh), (90, 90, 90), 1)

            if detection.bbox is not None:
                x, y, w, h = detection.bbox
                color = green if detection.present else (0, 200, 255)
                cv2.rectangle(display, (x, y), (x + w, y + h), color, 3)
                cv2.putText(display, f"{detection.state} {detection.presence_score:.0%}", (x, max(24, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.60, color, 2, cv2.LINE_AA)
                if detail_enabled and detection.present:
                    for idx, region in enumerate(current_regions, start=1):
                        x1, y1 = x + region.x, y + region.y
                        x2, y2 = x1 + region.width, y1 + region.height
                        cv2.rectangle(display, (x1, y1), (x2, y2), green, 2)
                        cv2.putText(display, f"detail {idx}", (x1, max(18, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, green, 1, cv2.LINE_AA)

            if detector.collecting_background:
                done, total = detector.calibration_progress
                _draw_text_box(display, ["CALIBRATING EMPTY BACKGROUND", f"Frames: {done}/{total}", "Keep the station EMPTY"], "LOW_CONFIDENCE")
            elif not detector.calibrated and manual_bbox is None:
                _draw_text_box(display, ["BACKGROUND NOT CALIBRATED", "Remove piece and press B", "Classifier is paused"], "MANUAL_REVIEW")
            elif detection.state == "EMPTY":
                _draw_text_box(display, ["EMPTY - NO PIECE", f"Presence score: {detection.presence_score:.0%}", "Classifier paused"], "ACCEPTED")
            elif detection.state == "PIECE_CANDIDATE":
                _draw_text_box(display, ["PIECE CANDIDATE", f"Presence score: {detection.presence_score:.0%}", "Waiting for stable detection..."], "LOW_CONFIDENCE")
            elif current_result is not None:
                stable_prediction = _prediction_is_stable(prediction_history, stable_prediction_frames)
                if not stable_prediction:
                    _draw_text_box(display, ["PIECE PRESENT", "IDENTIFYING TYPE...", f"Inference: {last_inference_ms:.0f} ms"], "LOW_CONFIDENCE")
                else:
                    second = current_result.alternatives[0] if current_result.alternatives else None
                    margin = current_result.confidence - (second.confidence if second else 0.0)
                    lines = [
                        f"Type: {current_result.core_type}",
                        f"Confidence: {current_result.confidence:.1%}",
                        f"Status: {current_result.status}",
                        f"Top-1 margin: {margin:.1%}",
                        f"Piece score: {detection.presence_score:.0%}",
                        f"Inference: {last_inference_ms:.0f} ms",
                    ]
                    _draw_text_box(display, lines, current_result.status)

            if detail_enabled and current_detail is not None:
                _draw_crop_preview(display, current_detail, label="DETAIL FOCUS (GREEN)")
            elif current_crop is not None:
                _draw_crop_preview(display, current_crop)

            controls = "B:calibrate  R:manual ROI  C:clear ROI  X:clear bg  D:details  S:save  Q:quit"
            cv2.putText(display, controls, (20, display.shape[0] - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("b"):
                manual_bbox = None
                detector.start_calibration()
                probability_history.clear()
                prediction_history.clear()
                current_result = None
                print("Background calibration started. Keep the station empty.")
            elif key == ord("x"):
                detector.clear()
                manual_bbox = None
                probability_history.clear()
                prediction_history.clear()
                current_result = None
                print("Background cleared. Remove the piece and press B to recalibrate.")
            elif key == ord("r"):
                selected = _manual_roi(frame, "Select piece ROI and press ENTER")
                if selected is not None:
                    manual_bbox = selected
                    probability_history.clear()
                    prediction_history.clear()
                    current_result = None
                    print(f"Manual ROI active: {manual_bbox}")
            elif key == ord("c"):
                manual_bbox = None
                probability_history.clear()
                prediction_history.clear()
                current_result = None
                print("Manual ROI cleared.")
            elif key == ord("d"):
                detail_enabled = not detail_enabled
                current_detail = None
                current_regions = []
                print(f"Green detail focus: {'ON' if detail_enabled else 'OFF'}")
            elif key == ord("s"):
                if current_crop is None or current_crop.size == 0:
                    print("No stable piece crop to save.")
                else:
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    label = current_result.core_type if current_result else "piece"
                    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
                    destination = save_dir / f"{timestamp}_{safe}.jpg"
                    cv2.imwrite(str(destination), current_crop)
                    print(f"Saved: {destination}")
    finally:
        capture.release()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Robust live piece detection + core-type classification.")
    parser.add_argument("--artifact", default="artifacts/core_classifier_v2")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--camera-index", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    classifier = CoreClassifier(args.artifact)
    run_live_camera(classifier, config, camera_index=args.camera_index)


if __name__ == "__main__":
    main()
