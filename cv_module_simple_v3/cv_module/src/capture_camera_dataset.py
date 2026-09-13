from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from src.config import load_config
from src.live_camera import _open_camera, center_bbox, crop_bbox


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture labeled webcam crops to improve camera-domain classification."
    )
    parser.add_argument("--class-name", required=True, help="Existing class folder name under data/raw.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--camera-index", type=int, default=None)
    parser.add_argument("--create-class", action="store_true", help="Allow creating a missing class folder.")
    args = parser.parse_args()

    config = load_config(args.config)
    raw_dir = Path(config["dataset"]["raw_dir"])
    class_dir = raw_dir / args.class_name
    if not class_dir.exists():
        if args.create_class:
            class_dir.mkdir(parents=True, exist_ok=True)
        else:
            raise SystemExit(
                f"Class folder does not exist: {class_dir}\n"
                "Use the exact existing class name, or --create-class only when intentionally adding a class."
            )

    camera_cfg = config.get("camera", {})
    camera_index = int(args.camera_index if args.camera_index is not None else camera_cfg.get("index", 0))
    capture = _open_camera(camera_index)
    if not capture.isOpened():
        raise SystemExit(f"Could not open camera index {camera_index}.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(camera_cfg.get("width", 1280)))
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(camera_cfg.get("height", 720)))

    mirror = bool(camera_cfg.get("mirror", True))
    roi_w = float(camera_cfg.get("center_roi_width", 0.65))
    roi_h = float(camera_cfg.get("center_roi_height", 0.75))
    window = f"Capture training originals - {args.class_name}"
    saved = 0

    print("Capture independent views, not a burst of nearly identical frames.")
    print("Vary distance, small angle, position, and realistic lighting. SPACE/S=save ROI, Q/Esc=quit.")
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            if mirror:
                frame = cv2.flip(frame, 1)
            bbox = center_bbox(frame.shape, roi_w, roi_h)
            crop = crop_bbox(frame, bbox)
            display = frame.copy()
            x, y, width, height = bbox
            cv2.rectangle(display, (x, y), (x + width, y + height), (50, 220, 50), 2)
            cv2.putText(display, f"Class: {args.class_name} | saved: {saved}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 220, 50), 2, cv2.LINE_AA)
            cv2.putText(display, "SPACE/S save ROI | Q quit", (20, display.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.imshow(window, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("s"), 32):
                stamp = time.strftime("%Y%m%d_%H%M%S")
                destination = class_dir / f"camera_{stamp}_{saved:03d}.jpg"
                cv2.imwrite(str(destination), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                saved += 1
                print(f"Saved: {destination}")
                time.sleep(0.25)
    finally:
        capture.release()
        cv2.destroyAllWindows()
    print(f"Saved {saved} image(s) to {class_dir}")


if __name__ == "__main__":
    main()
