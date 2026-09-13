from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import cv2


VideoSourceValue = Union[int, str]


@dataclass(frozen=True)
class ParsedVideoSource:
    value: VideoSourceValue
    is_network: bool
    display_name: str


def parse_video_source(source: str | int | None, default_index: int = 0) -> ParsedVideoSource:
    """Parse a local webcam index or a phone/network camera URL.

    Examples:
      0                               -> local webcam index 0
      "1"                             -> local webcam index 1
      "http://192.168.1.50:8080/video" -> MJPEG/HTTP phone stream
      "rtsp://192.168.1.50:8554/live"  -> RTSP phone stream
    """
    if source is None:
        return ParsedVideoSource(default_index, False, f"camera {default_index}")
    if isinstance(source, int):
        return ParsedVideoSource(source, False, f"camera {source}")

    value = str(source).strip()
    if not value:
        return ParsedVideoSource(default_index, False, f"camera {default_index}")
    if value.isdigit():
        index = int(value)
        return ParsedVideoSource(index, False, f"camera {index}")

    lower = value.lower()
    is_network = lower.startswith(("http://", "https://", "rtsp://", "rtmp://", "udp://", "tcp://"))
    return ParsedVideoSource(value, is_network, value)


def open_video_source(source: ParsedVideoSource) -> cv2.VideoCapture:
    """Open a local webcam or network camera stream with OpenCV.

    Local Windows webcams try DirectShow first. Network streams are passed directly
    to OpenCV/FFmpeg so common MJPEG and RTSP phone-camera URLs work without a
    project-specific phone app dependency.
    """
    if isinstance(source.value, int):
        if hasattr(cv2, "CAP_DSHOW"):
            capture = cv2.VideoCapture(source.value, cv2.CAP_DSHOW)
            if capture.isOpened():
                return capture
            capture.release()
        return cv2.VideoCapture(source.value)

    return cv2.VideoCapture(source.value)
