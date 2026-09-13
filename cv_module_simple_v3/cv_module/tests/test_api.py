import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), color=(100, 120, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_health_model_info_and_classify(dummy_artifact: Path) -> None:
    app = create_app(dummy_artifact)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["model_loaded"] is True

        info = client.get("/model-info")
        assert info.status_code == 200
        assert info.json()["num_classes"] == 5

        response = client.post(
            "/api/v1/classify",
            files={"image": ("sample.png", _png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["prediction"]["core_type"] in info.json()["known_classes"]
        assert body["status"] in {"ACCEPTED", "LOW_CONFIDENCE", "MANUAL_REVIEW"}
        assert body["model_version"] == "core_classifier_test"


def test_malformed_upload_is_rejected(dummy_artifact: Path) -> None:
    app = create_app(dummy_artifact)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/classify",
            files={"image": ("broken.png", b"not an image", "image/png")},
        )
        assert response.status_code == 400


def test_wrong_content_type_is_rejected(dummy_artifact: Path) -> None:
    app = create_app(dummy_artifact)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/classify",
            files={"image": ("file.txt", b"abc", "text/plain")},
        )
        assert response.status_code == 415
