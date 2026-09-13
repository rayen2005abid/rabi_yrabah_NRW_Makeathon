from __future__ import annotations

import argparse
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from src.config import load_config
from src.inference import CoreClassifier
from src.live_camera import _open_camera, crop_bbox, frame_to_pil
from src.piece_detection import BBox, center_zone


def fixed_roi(frame_shape: tuple[int, ...], width_fraction: float, height_fraction: float) -> BBox:
    """Return the fixed central work area used for both capture and inference."""
    return center_zone(frame_shape, width_fraction, height_fraction)


def average_probabilities(history: deque[np.ndarray]) -> np.ndarray:
    if not history:
        raise ValueError("Probability history is empty")
    probs = np.stack(list(history), axis=0).mean(axis=0)
    total = float(probs.sum())
    return probs / total if total > 0 else probs


def camera_decision(
    probabilities: np.ndarray,
    class_names: list[str],
    empty_class_name: str,
    empty_threshold: float,
    type_threshold: float,
    minimum_top1_margin: float,
) -> tuple[str, str, float, float]:
    """Convert averaged class probabilities into a simple operational state.

    Returns (state, label, top1_confidence, top1_minus_top2_margin).
    States are EMPTY, PIECE, or UNCERTAIN.
    """
    order = np.argsort(probabilities)[::-1]
    top1 = int(order[0])
    top2 = int(order[1]) if len(order) > 1 else top1
    label = class_names[top1]
    confidence = float(probabilities[top1])
    margin = float(probabilities[top1] - probabilities[top2]) if top2 != top1 else confidence

    if label == empty_class_name:
        return ("EMPTY" if confidence >= empty_threshold else "UNCERTAIN", label, confidence, margin)
    if confidence >= type_threshold and margin >= minimum_top1_margin:
        return "PIECE", label, confidence, margin
    return "UNCERTAIN", label, confidence, margin


def _draw_panel(frame: np.ndarray, lines: list[str], color: tuple[int, int, int]) -> None:
    x, y = 20, 35
    line_h = 29
    panel_w = 500
    panel_h = 28 + line_h * len(lines)
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (10 + panel_w, 10 + panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.62, frame, 0.38, 0, frame)
    for i, text in enumerate(lines):
        cv2.putText(
            frame,
            text,
            (x, y + i * line_h),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            color if i < 2 else (235, 235, 235),
            2,
            cv2.LINE_AA,
        )


def run_camera(config_path: str, artifact_path: str, camera_index: int | None = None) -> None:
    config = load_config(config_path)
    camera_cfg = config.get("simple_camera", {})
    classifier = CoreClassifier(artifact_path)

    empty_name = str(camera_cfg.get("empty_class_name", "EMPTY"))
    if empty_name not in classifier.class_names:
        raise RuntimeError(
            f"The simple camera requires an '{empty_name}' training class, but the model knows: "
            f"{classifier.class_names}. Capture EMPTY images and retrain the simple_v3 model."
        )

    index = int(camera_cfg.get("index", 0) if camera_index is None else camera_index)
    width = int(camera_cfg.get("width", 1280))
    height = int(camera_cfg.get("height", 720))
    mirror = bool(camera_cfg.get("mirror", True))
    roi_w = float(camera_cfg.get("roi_width_fraction", 0.55))
    roi_h = float(camera_cfg.get("roi_height_fraction", 0.72))
    every = max(1, int(camera_cfg.get("inference_every_n_frames", 3)))
    smoothing = max(1, int(camera_cfg.get("smoothing_window", 7)))
    stable_frames = max(1, int(camera_cfg.get("stable_frames", 3)))
    empty_threshold = float(camera_cfg.get("empty_threshold", 0.60))
    type_threshold = float(camera_cfg.get("type_threshold", 0.65))
    min_margin = float(camera_cfg.get("minimum_top1_margin", 0.08))
    save_dir = Path(camera_cfg.get("save_dir", "reports/camera_captures"))
    save_dir.mkdir(parents=True, exist_ok=True)

    cap = _open_camera(index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera {index}. Try --camera-index 1.")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    history: deque[np.ndarray] = deque(maxlen=smoothing)
    state_history: deque[str] = deque(maxlen=stable_frames)
    latest_probs: np.ndarray | None = None
    latest_state = "UNCERTAIN"
    latest_label = "-"
    latest_conf = 0.0
    latest_margin = 0.0
    frame_no = 0
    last_ms = 0.0
    green = (40, 235, 40)
    yellow = (0, 220, 255)
    gray = (190, 190, 190)
    window = f"Simple Core Camera - {classifier.model_version}"

    print("Simple camera mode started.")
    print("Keep the core entirely inside the GREEN rectangle.")
    print(f"The model has one extra class named '{empty_name}' for NO PIECE.")
    print("Controls: S=save ROI | Q/ESC=quit")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.03)
                continue
            if mirror:
                frame = cv2.flip(frame, 1)
            frame_no += 1

            roi = fixed_roi(frame.shape, roi_w, roi_h)
            x, y, w, h = roi
            crop = crop_bbox(frame, roi)

            if frame_no % every == 0 and crop.size:
                started = time.perf_counter()
                result, diag = classifier.predict_with_diagnostics(frame_to_pil(crop), top_k=len(classifier.class_names))
                latest_probs = np.asarray(diag.combined_probabilities, dtype=np.float64)
                history.append(latest_probs)
                smoothed = average_probabilities(history)
                state, label, conf, margin = camera_decision(
                    smoothed,
                    classifier.class_names,
                    empty_name,
                    empty_threshold,
                    type_threshold,
                    min_margin,
                )
                state_history.append(state)
                # Only expose a stable state after repeated agreement.
                if len(state_history) == stable_frames and len(set(state_history)) == 1:
                    latest_state = state
                    latest_label = label
                    latest_conf = conf
                    latest_margin = margin
                else:
                    latest_state = "UNCERTAIN"
                    latest_label = label
                    latest_conf = conf
                    latest_margin = margin
                last_ms = (time.perf_counter() - started) * 1000.0

            display = frame.copy()
            cv2.rectangle(display, (x, y), (x + w, y + h), green, 4)
            cv2.putText(
                display,
                "PUT ONE PIECE INSIDE THIS GREEN BOX",
                (x, max(30, y - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                green,
                2,
                cv2.LINE_AA,
            )

            if latest_state == "EMPTY":
                lines = ["NO PIECE", f"EMPTY confidence: {latest_conf:.1%}", f"Inference: {last_ms:.0f} ms"]
                color = gray
            elif latest_state == "PIECE":
                lines = ["PIECE FOUND", f"Type: {latest_label}  ({latest_conf:.1%})", f"Margin: {latest_margin:.1%}", f"Inference: {last_ms:.0f} ms"]
                color = green
            else:
                lines = ["UNCERTAIN - HOLD PIECE STILL", f"Best guess: {latest_label}  ({latest_conf:.1%})", f"Margin: {latest_margin:.1%}", f"Inference: {last_ms:.0f} ms"]
                color = yellow
            _draw_panel(display, lines, color)

            cv2.imshow(window, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s") and crop.size:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                path = save_dir / f"roi_{stamp}.jpg"
                cv2.imwrite(str(path), crop)
                print(f"Saved ROI: {path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple fixed-ROI camera classifier.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--artifact", default="artifacts/core_classifier_simple_v3")
    parser.add_argument("--camera-index", type=int, default=None)
    args = parser.parse_args()
    run_camera(args.config, args.artifact, args.camera_index)


if __name__ == "__main__":
    main()
