from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import UnidentifiedImageError

from src.inference import CoreClassifier, _result_to_api_shape


def create_app(artifact_dir: str | Path | None = None) -> FastAPI:
    resolved_artifact = Path(
        artifact_dir or os.environ.get("CORE_CLASSIFIER_ARTIFACT", "artifacts/core_classifier_simple_v3")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.classifier = None
        app.state.load_error = None
        try:
            # Loaded exactly once at application startup. No training is ever triggered here.
            app.state.classifier = CoreClassifier(resolved_artifact)
        except Exception as exc:
            app.state.load_error = f"{type(exc).__name__}: {exc}"
        yield
        app.state.classifier = None

    app = FastAPI(
        title="Smart Core Warehouse CV API",
        version="1.0.0",
        description="CV Module V1: foundry-core type classification.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict:
        classifier = app.state.classifier
        return {
            "status": "ok" if classifier is not None else "degraded",
            "model_loaded": classifier is not None,
            "model_version": classifier.model_version if classifier else None,
            "error": app.state.load_error,
        }

    @app.get("/model-info")
    def model_info() -> dict:
        classifier = app.state.classifier
        if classifier is None:
            raise HTTPException(status_code=503, detail=f"Model is not loaded: {app.state.load_error}")
        return classifier.model_info()

    @app.post("/api/v1/classify")
    async def classify(image: UploadFile = File(...)) -> dict:
        classifier = app.state.classifier
        if classifier is None:
            raise HTTPException(status_code=503, detail=f"Model is not loaded: {app.state.load_error}")
        if not image.content_type or not image.content_type.lower().startswith("image/"):
            raise HTTPException(status_code=415, detail="Upload must use an image/* content type.")
        payload = await image.read()
        max_bytes = int(classifier.config["inference"].get("max_upload_mb", 10)) * 1024 * 1024
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded image is empty.")
        if len(payload) > max_bytes:
            raise HTTPException(status_code=413, detail="Uploaded image exceeds configured size limit.")
        try:
            result = classifier.predict_bytes(payload)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Malformed or unsupported image: {exc}") from exc
        return _result_to_api_shape(result)

    return app


app = create_app()
