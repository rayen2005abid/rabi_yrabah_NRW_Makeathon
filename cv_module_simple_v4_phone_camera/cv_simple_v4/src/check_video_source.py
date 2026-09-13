from __future__ import annotations

import argparse
import time

import cv2

from src.video_source import open_video_source, parse_video_source


def main() -> None:
    parser = argparse.ArgumentParser(description="Test a webcam or phone/network camera source without loading the ML model.")
    parser.add_argument("--source", required=True, help="Webcam index or stream URL.")
    parser.add_argument("--frames", type=int, default=60, help="Number of frames to read before declaring success.")
    parser.add_argument("--show", action="store_true", help="Display the incoming stream while testing.")
    args = parser.parse_args()

    source = parse_video_source(args.source)
    cap = open_video_source(source)
    if not cap.isOpened():
        raise SystemExit(
            f"FAILED: could not open {source.display_name}. Verify the URL in a PC browser/player and confirm phone/PC network access."
        )

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    target = max(1, int(args.frames))
    good = 0
    failures = 0
    started = time.perf_counter()
    first_shape = None

    try:
        while good < target and failures < 60:
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                time.sleep(0.03)
                continue
            good += 1
            if first_shape is None:
                first_shape = frame.shape
            if args.show:
                cv2.imshow("Phone/Video Source Test - Q to quit", frame)
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    elapsed = max(time.perf_counter() - started, 1e-6)
    if good == 0:
        raise SystemExit("FAILED: source opened but no readable frames were received.")

    h, w = first_shape[:2] if first_shape else (0, 0)
    print("VIDEO SOURCE OK")
    print(f"Source: {source.display_name}")
    print(f"Readable frames: {good}")
    print(f"Resolution: {w}x{h}")
    print(f"Approx receive FPS: {good / elapsed:.1f}")
    if failures:
        print(f"Temporary read failures: {failures}")


if __name__ == "__main__":
    main()
