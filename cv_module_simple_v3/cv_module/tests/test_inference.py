from pathlib import Path

from PIL import Image

from src.inference import CoreClassifier, confidence_status


def test_confidence_status_mapping() -> None:
    assert confidence_status(0.80, 0.80, 0.60) == "ACCEPTED"
    assert confidence_status(0.79, 0.80, 0.60) == "LOW_CONFIDENCE"
    assert confidence_status(0.60, 0.80, 0.60) == "LOW_CONFIDENCE"
    assert confidence_status(0.59, 0.80, 0.60) == "MANUAL_REVIEW"


def test_inference_from_dummy_artifact(dummy_artifact: Path) -> None:
    classifier = CoreClassifier(dummy_artifact, device="cpu")
    image = Image.new("RGB", (96, 72), color=(120, 100, 80))
    result = classifier.predict_pil(image, top_k=5)
    probabilities = [result.confidence] + [item.confidence for item in result.alternatives]
    assert result.core_type in classifier.class_names
    assert len(probabilities) == 5
    assert abs(sum(probabilities) - 1.0) < 1e-5
    assert result.model_version == "core_classifier_test"
