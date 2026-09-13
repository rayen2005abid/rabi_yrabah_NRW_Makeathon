import numpy as np

from src.inference import ClassificationResult, ClassProbability
from src.live_camera import (
    ForegroundObjectLocator,
    _result_to_probability_vector,
    center_bbox,
    crop_bbox,
    smooth_probability_history,
)


def test_probability_vector_uses_class_order() -> None:
    result = ClassificationResult(
        core_type="B",
        confidence=0.60,
        alternatives=[ClassProbability("A", 0.25), ClassProbability("C", 0.15)],
        status="LOW_CONFIDENCE",
        model_version="test",
    )
    vector = _result_to_probability_vector(result, ["A", "B", "C"])
    assert np.allclose(vector, [0.25, 0.60, 0.15])


def test_temporal_smoothing_and_status() -> None:
    history = [np.asarray([0.70, 0.20, 0.10]), np.asarray([0.90, 0.05, 0.05])]
    result = smooth_probability_history(
        history=history,
        class_names=["CORE_A", "CORE_B", "CORE_C"],
        accept_threshold=0.80,
        review_threshold=0.60,
        model_version="core_classifier_test",
        top_k=3,
    )
    assert result.core_type == "CORE_A"
    assert abs(result.confidence - 0.80) < 1e-9
    assert result.status == "ACCEPTED"
    assert len(result.alternatives) == 2


def test_center_bbox_and_crop() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    bbox = center_bbox(frame.shape, width_fraction=0.5, height_fraction=0.6)
    assert bbox == (50, 20, 100, 60)
    crop = crop_bbox(frame, bbox)
    assert crop.shape == (60, 100, 3)


def test_foreground_locator_finds_large_object_after_calibration() -> None:
    background = np.full((240, 320, 3), 220, dtype=np.uint8)
    frame = background.copy()
    frame[70:190, 100:230] = (30, 30, 30)
    locator = ForegroundObjectLocator(
        threshold=20,
        min_area_ratio=0.02,
        max_area_ratio=0.9,
        margin=0.0,
        blur_kernel=3,
        morph_kernel=3,
    )
    locator.set_background(background)
    located = locator.detect(frame)
    assert located is not None
    x, y, w, h = located.bbox
    assert x <= 105 and y <= 75
    assert x + w >= 225 and y + h >= 185
    assert located.method == "BACKGROUND"


def test_foreground_locator_returns_none_for_empty_scene() -> None:
    background = np.full((120, 160, 3), 180, dtype=np.uint8)
    locator = ForegroundObjectLocator(threshold=20, blur_kernel=3, morph_kernel=3)
    locator.set_background(background)
    assert locator.detect(background.copy()) is None


def test_piece_presence_detector_requires_stable_frames() -> None:
    from src.piece_detection import PiecePresenceDetector

    background = np.full((240, 320, 3), 220, dtype=np.uint8)
    piece = background.copy()
    piece[75:190, 105:225] = (35, 35, 35)
    detector = PiecePresenceDetector(
        calibration_frames=3,
        detection_zone_width=1.0,
        detection_zone_height=1.0,
        diff_threshold=20,
        min_foreground_ratio=0.005,
        min_component_area_ratio=0.01,
        max_component_area_ratio=0.9,
        enter_frames=3,
        exit_frames=2,
        bbox_margin=0.0,
        blur_kernel=3,
        morph_kernel=3,
        min_presence_score=0.05,
        adaptive_background_rate=0.0,
    )
    detector.start_calibration()
    for _ in range(3):
        detector.add_calibration_frame(background)

    first = detector.update(piece)
    second = detector.update(piece)
    third = detector.update(piece)
    assert first.present is False
    assert second.present is False
    assert third.present is True
    assert third.state == "PIECE_PRESENT"
    assert third.bbox is not None

    detector.update(background)
    cleared = detector.update(background)
    assert cleared.present is False
    assert cleared.state == "EMPTY"
