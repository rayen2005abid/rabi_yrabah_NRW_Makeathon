from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from src.config import load_config
from src.live_camera import _open_camera, crop_bbox
from src.simple_camera import fixed_roi


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture training images from the exact camera ROI used at inference.")
    parser.add_argument("--class-name", required=True, help="One real core type folder name or EMPTY.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--camera-index", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    cfg = config.get("simple_camera", {})
    raw_dir = Path(config["dataset"]["raw_dir"])
    output_dir = raw_dir / args.class_name
    output_dir.mkdir(parents=True, exist_ok=True)

    index = int(cfg.get("index", 0) if args.camera_index is None else args.camera_index)
    width = int(cfg.get("width", 1280))
    height = int(cfg.get("height", 720))
    mirror = bool(cfg.get("mirror", True))
    roi_w = float(cfg.get("roi_width_fraction", 0.55))
    roi_h = float(cfg.get("roi_height_fraction", 0.72))

    cap = _open_camera(index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera {index}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    print(f"Capturing class: {args.class_name}")
    if args.class_name.upper() == str(cfg.get("empty_class_name", "EMPTY")).upper():
        print("Keep the GREEN box EMPTY. Change normal lighting/background slightly between captures.")
    else:
        print("Put ONE piece fully inside the GREEN box. Move/rotate it between captures.")
    print("SPACE/S = save one ROI image | Q/ESC = quit")

    count = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            if mirror:
                frame = cv2.flip(frame, 1)
            roi = fixed_roi(frame.shape, roi_w, roi_h)
            x, y, w, h = roi
            crop = crop_bbox(frame, roi)
            display = frame.copy()
            cv2.rectangle(display, (x, y), (x + w, y + h), (40, 235, 40), 4)
            cv2.putText(display, f"CLASS: {args.class_name} | saved: {count}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (40, 235, 40), 2, cv2.LINE_AA)
            cv2.putText(display, "SPACE/S save | Q quit", (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (230, 230, 230), 2, cv2.LINE_AA)
            cv2.imshow("Capture ROI Dataset", display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("s"), 32) and crop.size:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                millis = int((time.time() % 1) * 1000)
                path = output_dir / f"camera_{stamp}_{millis:03d}.jpg"
                cv2.imwrite(str(path), crop)
                count += 1
                print(f"Saved {path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
