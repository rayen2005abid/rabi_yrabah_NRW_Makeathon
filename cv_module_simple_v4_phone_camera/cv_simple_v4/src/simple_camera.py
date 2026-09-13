from __future__ import annotations

import argparse
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.config import load_config
from src.inference import CoreClassifier
from src.live_camera import crop_bbox, frame_to_pil
from src.video_source import open_video_source, parse_video_source
from src.piece_detection import BBox, center_zone


def fixed_roi(frame_shape: tuple[int, ...], width_fraction: float, height_fraction: float) -> BBox:
    """Return the fixed central work area used for both capture and inference."""
    return center_zone(frame_shape, width_fraction, height_fraction)


def average_probabilities(history: deque[np.ndarray] | list[np.ndarray]) -> np.ndarray:
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
    """Convert class probabilities into EMPTY / PIECE / UNCERTAIN."""
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


@dataclass
class VoteResult:
    state: str
    label: str
    confidence: float
    margin: float
    consensus: float
    second_label: str
    second_confidence: float


def vote_decision(
    history: list[np.ndarray] | deque[np.ndarray],
    class_names: list[str],
    empty_class_name: str,
    empty_threshold: float,
    type_threshold: float,
    minimum_top1_margin: float,
    minimum_consensus: float,
) -> VoteResult:
    """Decide from a burst of frames rather than trusting a single frame.

    We combine two checks:
    1) frame-level majority vote: most frames should agree on the same class;
    2) mean probabilities: the winning class must still be confident and separated
       from the second choice.

    This deliberately prefers UNCERTAIN over a fast but wrong industrial decision.
    """
    if not history:
        raise ValueError("Prediction history is empty")

    stacked = np.stack(list(history), axis=0)
    winners = np.argmax(stacked, axis=1)
    counts = Counter(int(index) for index in winners.tolist())
    winning_index, winning_count = counts.most_common(1)[0]
    consensus = winning_count / len(winners)

    averaged = stacked.mean(axis=0)
    averaged = averaged / max(float(averaged.sum()), 1e-12)
    order = np.argsort(averaged)[::-1]
    mean_top = int(order[0])
    # Prefer the majority-vote winner, but only if the mean distribution supports it.
    if mean_top != winning_index and float(averaged[winning_index]) < float(averaged[mean_top]) * 0.85:
        return VoteResult(
            state="UNCERTAIN",
            label=class_names[winning_index],
            confidence=float(averaged[winning_index]),
            margin=0.0,
            consensus=consensus,
            second_label=class_names[mean_top],
            second_confidence=float(averaged[mean_top]),
        )

    second_index = next((int(idx) for idx in order if int(idx) != winning_index), winning_index)
    confidence = float(averaged[winning_index])
    second_confidence = float(averaged[second_index])
    margin = confidence - second_confidence
    label = class_names[winning_index]
    second_label = class_names[second_index]

    if label == empty_class_name:
        state = "EMPTY" if consensus >= minimum_consensus and confidence >= empty_threshold else "UNCERTAIN"
    else:
        state = (
            "PIECE"
            if consensus >= minimum_consensus
            and confidence >= type_threshold
            and margin >= minimum_top1_margin
            else "UNCERTAIN"
        )

    return VoteResult(
        state=state,
        label=label,
        confidence=confidence,
        margin=margin,
        consensus=consensus,
        second_label=second_label,
        second_confidence=second_confidence,
    )


def _draw_panel(frame: np.ndarray, lines: list[str], color: tuple[int, int, int]) -> None:
    x, y = 20, 35
    line_h = 29
    panel_w = 560
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


def run_camera(
    config_path: str,
    artifact_path: str,
    camera_index: int | None = None,
    source: str | int | None = None,
    mirror_override: bool | None = None,
) -> None:
    config = load_config(config_path)
    camera_cfg = config.get("simple_camera", {})
    classifier = CoreClassifier(artifact_path)

    empty_name = str(camera_cfg.get("empty_class_name", "EMPTY"))
    if empty_name not in classifier.class_names:
        raise RuntimeError(
            f"The simple camera requires an '{empty_name}' training class, but the model knows: "
            f"{classifier.class_names}. Capture EMPTY images and retrain."
        )

    index = int(camera_cfg.get("index", 0) if camera_index is None else camera_index)
    parsed_source = parse_video_source(source if source is not None else index, default_index=index)
    width = int(camera_cfg.get("width", 1280))
    height = int(camera_cfg.get("height", 720))
    # Rear-phone-camera streams should normally NOT be mirrored. Local laptop webcams
    # retain the configured mirror behavior unless explicitly overridden.
    default_mirror = False if parsed_source.is_network else bool(camera_cfg.get("mirror", True))
    mirror = default_mirror if mirror_override is None else bool(mirror_override)
    roi_w = float(camera_cfg.get("roi_width_fraction", 0.55))
    roi_h = float(camera_cfg.get("roi_height_fraction", 0.72))

    scan_frames = max(3, int(camera_cfg.get("scan_frames", 12)))
    scan_every = max(1, int(camera_cfg.get("scan_every_n_frames", 2)))
    min_consensus = float(camera_cfg.get("minimum_consensus", 0.75))
    empty_threshold = float(camera_cfg.get("empty_threshold", 0.65))
    type_threshold = float(camera_cfg.get("type_threshold", 0.70))
    min_margin = float(camera_cfg.get("minimum_top1_margin", 0.10))

    save_dir = Path(camera_cfg.get("save_dir", "reports/camera_captures"))
    save_dir.mkdir(parents=True, exist_ok=True)

    cap = open_video_source(parsed_source)
    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open video source: {parsed_source.display_name}. "
            "For a phone stream, verify that phone and PC are on the same network, "
            "the stream URL is reachable in a PC browser, and the phone camera server is running."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    scanning = False
    scan_history: list[np.ndarray] = []
    result: VoteResult | None = None
    frame_no = 0
    last_ms = 0.0
    consecutive_read_failures = 0

    green = (40, 235, 40)
    yellow = (0, 220, 255)
    gray = (190, 190, 190)
    red = (30, 80, 240)
    window = f"Core Type Scanner - {classifier.model_version}"

    print("Simple scan mode started.")
    print(f"Video source: {parsed_source.display_name}")
    print(f"Mirror: {mirror}")
    print("1) Put exactly one piece fully inside the GREEN rectangle.")
    print("2) Hold it still.")
    print("3) Press SPACE once. The system votes across multiple frames.")
    print("Controls: SPACE=scan | S=save ROI | R=clear result | Q/ESC=quit")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_read_failures += 1
                if consecutive_read_failures >= 30:
                    print("Video stream interrupted; trying to reconnect...")
                    cap.release()
                    time.sleep(0.5)
                    cap = open_video_source(parsed_source)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    consecutive_read_failures = 0
                else:
                    time.sleep(0.03)
                continue
            consecutive_read_failures = 0
            if mirror:
                frame = cv2.flip(frame, 1)
            frame_no += 1

            roi = fixed_roi(frame.shape, roi_w, roi_h)
            x, y, w, h = roi
            crop = crop_bbox(frame, roi)

            if scanning and crop.size and frame_no % scan_every == 0:
                started = time.perf_counter()
                _, diag = classifier.predict_with_diagnostics(
                    frame_to_pil(crop), top_k=len(classifier.class_names)
                )
                scan_history.append(np.asarray(diag.combined_probabilities, dtype=np.float64))
                last_ms = (time.perf_counter() - started) * 1000.0

                if len(scan_history) >= scan_frames:
                    result = vote_decision(
                        scan_history,
                        classifier.class_names,
                        empty_name,
                        empty_threshold,
                        type_threshold,
                        min_margin,
                        min_consensus,
                    )
                    scanning = False

            display = frame.copy()
            cv2.rectangle(display, (x, y), (x + w, y + h), green, 4)
            cv2.putText(
                display,
                "PUT ONE PIECE HERE - HOLD STILL - PRESS SPACE",
                (x, max(30, y - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                green,
                2,
                cv2.LINE_AA,
            )

            if scanning:
                progress = min(len(scan_history), scan_frames)
                lines = [
                    "SCANNING... HOLD STILL",
                    f"Frames checked: {progress}/{scan_frames}",
                    "Do not move the piece until scan completes.",
                    f"Last inference: {last_ms:.0f} ms",
                ]
                color = yellow
            elif result is None:
                lines = [
                    "READY",
                    "Put one piece in the green box",
                    "Then press SPACE to identify it",
                    "The result uses multi-frame voting",
                ]
                color = green
            elif result.state == "EMPTY":
                lines = [
                    "NO PIECE DETECTED",
                    f"EMPTY confidence: {result.confidence:.1%}",
                    f"Frame agreement: {result.consensus:.0%}",
                    "Press SPACE to scan again",
                ]
                color = gray
            elif result.state == "PIECE":
                lines = [
                    "PIECE IDENTIFIED",
                    f"Type: {result.label}  ({result.confidence:.1%})",
                    f"Agreement: {result.consensus:.0%}  Margin: {result.margin:.1%}",
                    f"2nd: {result.second_label}  ({result.second_confidence:.1%})",
                    "Press SPACE to scan the next piece",
                ]
                color = green
            else:
                lines = [
                    "NOT SURE - SCAN AGAIN",
                    f"Best guess: {result.label}  ({result.confidence:.1%})",
                    f"Agreement: {result.consensus:.0%}  Margin: {result.margin:.1%}",
                    f"2nd: {result.second_label}  ({result.second_confidence:.1%})",
                    "Center the piece and press SPACE again",
                ]
                color = red

            _draw_panel(display, lines, color)
            cv2.imshow(window, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == 32:  # SPACE
                if not scanning:
                    scanning = True
                    scan_history.clear()
                    result = None
            elif key == ord("r"):
                scanning = False
                scan_history.clear()
                result = None
            elif key == ord("s") and crop.size:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                path = save_dir / f"roi_{stamp}.jpg"
                cv2.imwrite(str(path), crop)
                print(f"Saved ROI: {path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fixed-ROI multi-frame core type scanner.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--artifact", default="artifacts/core_classifier_simple_v4")
    parser.add_argument("--camera-index", type=int, default=None, help="Legacy local webcam index.")
    parser.add_argument(
        "--source",
        default=None,
        help="Video source: webcam index (0/1/2) or phone stream URL such as http://PHONE_IP:8080/video.",
    )
    mirror_group = parser.add_mutually_exclusive_group()
    mirror_group.add_argument("--mirror", action="store_true", help="Force horizontal mirroring.")
    mirror_group.add_argument("--no-mirror", action="store_true", help="Force natural, non-mirrored video.")
    args = parser.parse_args()
    mirror_override = True if args.mirror else (False if args.no_mirror else None)
    run_camera(args.config, args.artifact, args.camera_index, args.source, mirror_override)


if __name__ == "__main__":
    main()
