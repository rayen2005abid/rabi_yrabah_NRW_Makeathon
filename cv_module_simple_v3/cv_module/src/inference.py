from __future__ import annotations

import argparse
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import torch
import torch.nn.functional as F
from PIL import Image

from src.augmentations import build_eval_transform
from src.config import load_config
from src.models import build_model, extract_feature_embedding, gradcam_target_layer
from src.utils import load_json, verify_image


@dataclass
class ClassProbability:
    core_type: str
    confidence: float


@dataclass
class ClassificationResult:
    core_type: str
    confidence: float
    alternatives: list[ClassProbability]
    status: str
    model_version: str
    # Reserved extension points for future CV counting modules.
    quantity: int | None = None
    count_confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PredictionDiagnostics:
    """Secondary signals used for debugging and live-camera detail display."""

    classifier_probabilities: list[float]
    prototype_probabilities: list[float] | None
    combined_probabilities: list[float]
    prototype_assist_used: bool


def confidence_status(confidence: float, accept_threshold: float, review_threshold: float) -> str:
    if confidence >= accept_threshold:
        return "ACCEPTED"
    if confidence >= review_threshold:
        return "LOW_CONFIDENCE"
    return "MANUAL_REVIEW"


class CoreClassifier:
    """Load one versioned classifier and perform deterministic inference.

    If ``feature_prototypes.pt`` exists in the artifact, a small configurable share
    of the final score can come from cosine similarity to one TRAIN-only visual
    prototype per class. This is useful for a small industrial dataset because it
    asks both "what does the classifier head say?" and "which learned class visual
    fingerprint is this image closest to?". It never uses validation/test images.
    """

    def __init__(self, artifact_dir: str | Path, device: str | torch.device | None = None) -> None:
        self.artifact_dir = Path(artifact_dir)
        required = ["model.pt", "class_mapping.json", "config_snapshot.yaml"]
        missing = [name for name in required if not (self.artifact_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"Incomplete model artifact at {self.artifact_dir}; missing: {missing}")

        self.config = load_config(self.artifact_dir / "config_snapshot.yaml")
        self.class_mapping = load_json(self.artifact_dir / "class_mapping.json")
        self.class_names = [name for name, _ in sorted(self.class_mapping.items(), key=lambda item: item[1])]
        self.metadata = load_json(self.artifact_dir / "metadata.json") if (self.artifact_dir / "metadata.json").exists() else {}
        self.device = torch.device(device) if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        payload = torch.load(self.artifact_dir / "model.pt", map_location=self.device, weights_only=False)
        self.model_version = str(payload.get("model_version", self.metadata.get("model_version", "unknown")))
        self.architecture = str(payload["architecture"])
        self.image_size = int(payload["image_size"])
        self.model = build_model(
            architecture=self.architecture,
            num_classes=int(payload["num_classes"]),
            pretrained=False,
            dropout=float(payload.get("dropout", 0.2)),
        )
        self.model.load_state_dict(payload["model_state_dict"])
        self.model.to(self.device)
        self.model.eval()
        thresholds = payload.get("thresholds") or self.metadata.get("thresholds") or {}
        self.accept_threshold = float(thresholds.get("accept_threshold", self.config["inference"]["accept_threshold"]))
        self.review_threshold = float(thresholds.get("review_threshold", self.config["inference"]["review_threshold"]))
        self.transform = build_eval_transform(self.config)

        prototype_cfg = self.config.get("inference", {}).get("prototype_assist", {})
        self.prototype_weight = float(prototype_cfg.get("weight", 0.25))
        self.prototype_temperature = max(1e-3, float(prototype_cfg.get("temperature", 0.12)))
        self.prototype_enabled = bool(prototype_cfg.get("enabled", True))
        self.prototype_tensor: torch.Tensor | None = None
        self.prototype_counts: dict[str, int] = {}
        prototype_path = self.artifact_dir / "feature_prototypes.pt"
        if prototype_path.exists():
            bank = torch.load(prototype_path, map_location=self.device, weights_only=False)
            bank_classes = [str(item) for item in bank.get("class_names", [])]
            prototypes = bank.get("prototypes")
            if bank_classes == self.class_names and isinstance(prototypes, torch.Tensor):
                self.prototype_tensor = F.normalize(prototypes.to(self.device).float(), p=2, dim=1)
                self.prototype_counts = {str(k): int(v) for k, v in bank.get("counts", {}).items()}
                if "selected_weight" in bank:
                    self.prototype_weight = float(bank["selected_weight"])
                if "temperature" in bank:
                    self.prototype_temperature = max(1e-3, float(bank["temperature"]))
                if bank.get("validated_enabled") is False:
                    self.prototype_enabled = False
            else:
                raise ValueError(
                    "feature_prototypes.pt does not match the artifact class mapping; rebuild it with "
                    "python -m src.feature_prototypes --artifact <artifact>."
                )

    @property
    def prototype_assist_available(self) -> bool:
        return self.prototype_enabled and self.prototype_tensor is not None

    def _prepare_tensor(self, image: Image.Image) -> torch.Tensor:
        return self.transform(image.convert("RGB")).unsqueeze(0).to(self.device)

    def _probabilities_from_tensor(self, tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor | None, torch.Tensor]:
        with torch.no_grad():
            classifier_probabilities = torch.softmax(self.model(tensor), dim=1)[0]
            prototype_probabilities: torch.Tensor | None = None
            combined = classifier_probabilities
            if self.prototype_assist_available:
                embedding = extract_feature_embedding(self.model, self.architecture, tensor)
                similarities = embedding @ self.prototype_tensor.T
                prototype_probabilities = torch.softmax(similarities[0] / self.prototype_temperature, dim=0)
                weight = min(0.50, max(0.0, self.prototype_weight))
                combined = (1.0 - weight) * classifier_probabilities + weight * prototype_probabilities
                combined = combined / combined.sum().clamp_min(1e-12)
        return classifier_probabilities, prototype_probabilities, combined

    def predict_with_diagnostics(
        self,
        image: Image.Image,
        top_k: int | None = None,
    ) -> tuple[ClassificationResult, PredictionDiagnostics]:
        tensor = self._prepare_tensor(image)
        model_probs, prototype_probs, probabilities = self._probabilities_from_tensor(tensor)
        requested = int(top_k or self.config["inference"].get("top_k", 3))
        k = max(1, min(requested, len(self.class_names)))
        values, indices = torch.topk(probabilities.detach().cpu(), k=k)
        ranking = [
            ClassProbability(self.class_names[int(index)], float(value))
            for value, index in zip(values.tolist(), indices.tolist())
        ]
        best = ranking[0]
        result = ClassificationResult(
            core_type=best.core_type,
            confidence=best.confidence,
            alternatives=ranking[1:],
            status=confidence_status(best.confidence, self.accept_threshold, self.review_threshold),
            model_version=self.model_version,
        )
        diagnostics = PredictionDiagnostics(
            classifier_probabilities=model_probs.detach().cpu().tolist(),
            prototype_probabilities=(prototype_probs.detach().cpu().tolist() if prototype_probs is not None else None),
            combined_probabilities=probabilities.detach().cpu().tolist(),
            prototype_assist_used=self.prototype_assist_available,
        )
        return result, diagnostics

    def predict_pil(self, image: Image.Image, top_k: int | None = None) -> ClassificationResult:
        result, _ = self.predict_with_diagnostics(image, top_k=top_k)
        return result

    def explain_pil(self, image: Image.Image, class_name: str | None = None) -> tuple[Any, str]:
        """Return a Grad-CAM attention map for a requested/predicted core type.

        The map answers *where* the CNN found evidence for that type. It is an
        explanation/diagnostic signal, not an additional ground-truth label.
        """
        from src.explainability import GradCAM

        tensor = self._prepare_tensor(image)
        class_index = None
        if class_name is not None:
            if class_name not in self.class_mapping:
                raise ValueError(f"Unknown class for explanation: {class_name}")
            class_index = int(self.class_mapping[class_name])
        cam = GradCAM(self.model, gradcam_target_layer(self.model, self.architecture))
        try:
            attention, target_index, _ = cam.generate(tensor, class_index=class_index)
        finally:
            cam.close()
        return attention, self.class_names[target_index]

    def predict_file(self, image_path: str | Path, top_k: int | None = None) -> ClassificationResult:
        path = Path(image_path)
        with Image.open(path) as image:
            return self.predict_pil(image, top_k=top_k)

    def predict_bytes(self, payload: bytes, top_k: int | None = None) -> ClassificationResult:
        with Image.open(io.BytesIO(payload)) as image:
            return self.predict_pil(image, top_k=top_k)

    def model_info(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "architecture": self.architecture,
            "known_classes": self.class_names,
            "num_classes": len(self.class_names),
            "image_size": self.image_size,
            "thresholds": {
                "accept_threshold": self.accept_threshold,
                "review_threshold": self.review_threshold,
            },
            "prototype_assist": {
                "available": self.prototype_tensor is not None,
                "enabled": self.prototype_assist_available,
                "weight": self.prototype_weight,
                "temperature": self.prototype_temperature,
                "train_counts": self.prototype_counts,
            },
        }


def _result_to_api_shape(result: ClassificationResult) -> dict[str, Any]:
    return {
        "prediction": {"core_type": result.core_type, "confidence": result.confidence},
        "alternatives": [asdict(item) for item in result.alternatives],
        "status": result.status,
        "model_version": result.model_version,
        "quantity": result.quantity,
        "count_confidence": result.count_confidence,
    }


def batch_inference(
    classifier: CoreClassifier,
    input_dir: str | Path,
    output_csv: str | Path,
    top_k: int | None = None,
) -> tuple[Path, Path, int, int]:
    input_dir = Path(input_dir)
    output_csv = Path(output_csv)
    supported = {ext.lower() for ext in classifier.config["dataset"]["supported_extensions"]}
    files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in supported)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for path in files:
        valid, error, _ = verify_image(path)
        if not valid:
            failures.append({"file": str(path), "error": error or "invalid image"})
            continue
        try:
            result = classifier.predict_file(path, top_k=top_k)
            row: dict[str, Any] = {
                "file": str(path),
                "predicted_class": result.core_type,
                "confidence": result.confidence,
                "status": result.status,
                "model_version": result.model_version,
            }
            for index, alternative in enumerate(result.alternatives, start=2):
                row[f"top_{index}_class"] = alternative.core_type
                row[f"top_{index}_confidence"] = alternative.confidence
            rows.append(row)
        except Exception as exc:
            failures.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_csv, index=False)
    failures_path = output_csv.with_name(f"{output_csv.stem}_failures.csv")
    pd.DataFrame(failures, columns=["file", "error"]).to_csv(failures_path, index=False)
    return output_csv, failures_path, len(rows), len(failures)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run single-image or batch core-type inference.")
    parser.add_argument("--artifact", default="artifacts/core_classifier_v2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image")
    group.add_argument("--input-dir")
    parser.add_argument("--output", default="predictions.csv", help="Batch CSV output path.")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    classifier = CoreClassifier(args.artifact)
    if args.image:
        result = classifier.predict_file(args.image, top_k=args.top_k)
        if args.json_output:
            print(json.dumps(_result_to_api_shape(result), indent=2))
        else:
            print(f"Prediction: {result.core_type}")
            print(f"Confidence: {result.confidence:.2%}")
            print(f"Status: {result.status}")
            if result.alternatives:
                print("\nAlternatives:")
                for alternative in result.alternatives:
                    print(f"{alternative.core_type}: {alternative.confidence:.2%}")
            if classifier.prototype_assist_available:
                print(f"Detail-prototype assist: ON ({classifier.prototype_weight:.0%} blend)")
    else:
        output, failures, success_count, failure_count = batch_inference(
            classifier, args.input_dir, args.output, top_k=args.top_k
        )
        print(f"Batch complete: {success_count} success, {failure_count} failure(s)")
        print(f"Predictions: {output}")
        print(f"Failures: {failures}")


if __name__ == "__main__":
    main()
