from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from PIL import Image
from sklearn.metrics import accuracy_score, f1_score

from src.augmentations import build_eval_transform
from src.config import load_config
from src.models import build_model, extract_feature_embedding
from src.utils import load_json


def _collect_embedding_and_probabilities(
    rows: pd.DataFrame,
    raw_dir: Path,
    transform,
    model: torch.nn.Module,
    architecture: str,
    device: torch.device,
    class_mapping: dict[str, int],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    embeddings: list[torch.Tensor] = []
    probabilities: list[torch.Tensor] = []
    labels: list[int] = []
    with torch.no_grad():
        for _, row in rows.iterrows():
            image_path = raw_dir / str(row["file"])
            with Image.open(image_path) as image:
                tensor = transform(image.convert("RGB")).unsqueeze(0).to(device)
            logits = model(tensor)
            probabilities.append(torch.softmax(logits, dim=1)[0].cpu())
            embeddings.append(extract_feature_embedding(model, architecture, tensor)[0].cpu())
            labels.append(int(class_mapping[str(row["class"])]))
    if not embeddings:
        return (
            torch.empty((0, 0), dtype=torch.float32),
            torch.empty((0, len(class_mapping)), dtype=torch.float32),
            torch.empty((0,), dtype=torch.long),
        )
    return torch.stack(embeddings), torch.stack(probabilities), torch.tensor(labels, dtype=torch.long)


def _select_prototype_weight(
    validation_embeddings: torch.Tensor,
    validation_classifier_probs: torch.Tensor,
    validation_labels: torch.Tensor,
    prototypes: torch.Tensor,
    temperature: float,
    configured_weight: float,
) -> tuple[float, dict[str, dict[str, float]]]:
    """Tune only the blend weight on validation originals; untouched test stays unseen."""
    if validation_labels.numel() == 0:
        weight = min(0.5, max(0.0, float(configured_weight)))
        return weight, {}

    similarities = torch.nn.functional.normalize(validation_embeddings, p=2, dim=1) @ torch.nn.functional.normalize(
        prototypes, p=2, dim=1
    ).T
    prototype_probs = torch.softmax(similarities / max(1e-3, float(temperature)), dim=1)
    candidate_weights = sorted(
        {
            0.0,
            0.10,
            0.20,
            round(min(0.5, max(0.0, float(configured_weight))), 4),
            0.30,
            0.40,
        }
    )
    y_true = validation_labels.numpy()
    results: dict[str, dict[str, float]] = {}
    best_weight = 0.0
    best_key = (-1.0, -1.0, 0.0)
    for weight in candidate_weights:
        combined = (1.0 - weight) * validation_classifier_probs + weight * prototype_probs
        predicted = combined.argmax(dim=1).numpy()
        macro_f1 = float(f1_score(y_true, predicted, average="macro", zero_division=0))
        accuracy = float(accuracy_score(y_true, predicted))
        results[f"{weight:.2f}"] = {"macro_f1": macro_f1, "accuracy": accuracy}
        # Prefer higher F1, then accuracy; for exact ties prefer less prototype influence.
        key = (macro_f1, accuracy, -weight)
        if key > best_key:
            best_key = key
            best_weight = float(weight)
    return best_weight, results


def build_feature_prototypes(
    artifact_dir: str | Path,
    config: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
) -> Path:
    """Build and validation-calibrate one deep visual prototype per core type.

    Prototypes use TRAIN originals only. The optional blend weight is selected using
    VALIDATION originals only. TEST originals are never used here.
    """
    artifact_dir = Path(artifact_dir)
    if config is None:
        config = load_config(artifact_dir / "config_snapshot.yaml")
    metadata = load_json(artifact_dir / "metadata.json") if (artifact_dir / "metadata.json").exists() else {}
    mapping = load_json(artifact_dir / "class_mapping.json")
    class_names = [name for name, _ in sorted(mapping.items(), key=lambda item: item[1])]
    if manifest_path is None:
        manifest_path = metadata.get("dataset_summary", {}).get("manifest") or config["dataset"].get("split_manifest")
    if not manifest_path:
        raise ValueError("A split manifest is required to build TRAIN-only class prototypes.")
    manifest = pd.read_csv(manifest_path)
    train_rows = manifest[manifest["split"] == "train"].copy()
    validation_rows = manifest[manifest["split"] == "val"].copy()
    if train_rows.empty:
        raise ValueError("The training split is empty; cannot build class prototypes.")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    payload = torch.load(artifact_dir / "model.pt", map_location=device, weights_only=False)
    architecture = str(payload["architecture"])
    model = build_model(
        architecture=architecture,
        num_classes=int(payload["num_classes"]),
        pretrained=False,
        dropout=float(payload.get("dropout", 0.2)),
    )
    model.load_state_dict(payload["model_state_dict"])
    model.to(device).eval()
    transform = build_eval_transform(config)
    raw_dir = Path(config["dataset"]["raw_dir"])

    train_embeddings, _, train_labels = _collect_embedding_and_probabilities(
        train_rows, raw_dir, transform, model, architecture, device, mapping
    )
    if train_embeddings.numel() == 0:
        raise ValueError("No usable TRAIN images were found for prototype extraction.")

    prototypes: list[torch.Tensor] = []
    counts: dict[str, int] = {}
    for class_name in class_names:
        class_index = int(mapping[class_name])
        class_vectors = train_embeddings[train_labels == class_index]
        if class_vectors.shape[0] == 0:
            raise ValueError(f"No TRAIN original exists for class {class_name}")
        prototype = torch.nn.functional.normalize(class_vectors.mean(dim=0, keepdim=True), p=2, dim=1)[0]
        prototypes.append(prototype)
        counts[class_name] = int(class_vectors.shape[0])
    prototype_tensor = torch.stack(prototypes, dim=0)

    validation_embeddings, validation_probs, validation_labels = _collect_embedding_and_probabilities(
        validation_rows, raw_dir, transform, model, architecture, device, mapping
    )
    prototype_cfg = config.get("inference", {}).get("prototype_assist", {})
    configured_weight = float(prototype_cfg.get("weight", 0.25))
    temperature = float(prototype_cfg.get("temperature", 0.12))
    selected_weight, validation_scores = _select_prototype_weight(
        validation_embeddings,
        validation_probs,
        validation_labels,
        prototype_tensor,
        temperature=temperature,
        configured_weight=configured_weight,
    )

    destination = artifact_dir / "feature_prototypes.pt"
    torch.save(
        {
            "class_names": class_names,
            "prototypes": prototype_tensor,
            "counts": counts,
            "source_split": "train",
            "weight_selection_split": "validation" if len(validation_rows) else None,
            "manifest": str(manifest_path),
            "architecture": architecture,
            "temperature": temperature,
            "configured_weight": configured_weight,
            "selected_weight": selected_weight,
            "validated_enabled": bool(selected_weight > 0.0),
            "validation_scores_by_weight": validation_scores,
            "validation_originals": int(len(validation_rows)),
        },
        destination,
    )
    print("\nVISUAL DETAIL PROTOTYPES BUILT")
    print("=" * 60)
    for class_name in class_names:
        print(f"{class_name}: {counts[class_name]} TRAIN originals")
    if validation_scores:
        print(f"Validation-selected prototype blend: {selected_weight:.0%}")
        base = validation_scores.get("0.00", {})
        chosen = validation_scores.get(f"{selected_weight:.2f}", {})
        if base and chosen:
            print(
                f"Validation macro-F1: base={base['macro_f1']:.3f} -> selected={chosen['macro_f1']:.3f}"
            )
    else:
        print(f"No validation originals available; using configured blend: {selected_weight:.0%}")
    print(f"Saved: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TRAIN-only visual feature prototypes for each core type.")
    parser.add_argument("--artifact", default="artifacts/core_classifier_v2")
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()
    build_feature_prototypes(args.artifact, manifest_path=args.manifest)


if __name__ == "__main__":
    main()
