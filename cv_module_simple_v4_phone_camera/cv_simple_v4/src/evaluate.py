from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from src.augmentations import build_eval_transform
from src.config import load_config
from src.dataset import CoreImageDataset
from src.metrics import classification_metrics, confusion, text_classification_report
from src.models import build_model, extract_feature_embedding
from src.utils import configure_logging, copy_preserving_name, load_json, save_json

LOGGER = logging.getLogger(__name__)


def _load_artifact_model(artifact_dir: Path, device: torch.device) -> tuple[torch.nn.Module, dict[str, Any]]:
    payload = torch.load(artifact_dir / "model.pt", map_location=device, weights_only=False)
    model = build_model(
        architecture=payload["architecture"],
        num_classes=int(payload["num_classes"]),
        pretrained=False,
        dropout=float(payload.get("dropout", 0.2)),
    )
    model.load_state_dict(payload["model_state_dict"])
    model.to(device)
    model.eval()
    return model, payload


def _plot_confusion_matrix(matrix: np.ndarray, class_names: list[str], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(6, len(class_names) * 1.2), max(5, len(class_names))))
    image = ax.imshow(matrix, interpolation="nearest")
    fig.colorbar(image, ax=ax)
    ax.set(
        xticks=np.arange(len(class_names)),
        yticks=np.arange(len(class_names)),
        xticklabels=class_names,
        yticklabels=class_names,
        ylabel="True class",
        xlabel="Predicted class",
        title="Untouched Test Set Confusion Matrix",
    )
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    threshold = matrix.max() / 2 if matrix.size and matrix.max() else 0
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            ax.text(col, row, str(matrix[row, col]), ha="center", va="center", color="white" if matrix[row, col] > threshold else "black")
    fig.tight_layout()
    fig.savefig(destination, dpi=160, bbox_inches="tight")
    plt.close(fig)


def evaluate_artifact(
    artifact_dir: str | Path,
    config: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    if config is None:
        snapshot = artifact_dir / "config_snapshot.yaml"
        config = load_config(snapshot)
    metadata = load_json(artifact_dir / "metadata.json") if (artifact_dir / "metadata.json").exists() else {}
    class_mapping = load_json(artifact_dir / "class_mapping.json")
    class_names = [name for name, _ in sorted(class_mapping.items(), key=lambda item: item[1])]

    if manifest_path is None:
        recorded = metadata.get("dataset_summary", {}).get("manifest")
        if not recorded:
            raise ValueError("No split manifest was provided and artifact metadata does not record one.")
        manifest_path = Path(recorded)
    manifest = pd.read_csv(manifest_path)
    raw_dir = Path(config["dataset"]["raw_dir"])
    test_dataset = CoreImageDataset(
        raw_dir,
        manifest,
        "test",
        build_eval_transform(config),
        class_mapping,
    )
    if len(test_dataset) == 0:
        raise ValueError("Test split is empty; evaluation requires untouched original test images.")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, payload = _load_artifact_model(artifact_dir, device)

    prototype_tensor = None
    prototype_weight = 0.0
    prototype_temperature = 0.12
    prototype_path = artifact_dir / "feature_prototypes.pt"
    prototype_cfg = config.get("inference", {}).get("prototype_assist", {})
    prototype_config_enabled = bool(prototype_cfg.get("enabled", True))
    if prototype_path.exists() and prototype_config_enabled:
        bank = torch.load(prototype_path, map_location=device, weights_only=False)
        if [str(item) for item in bank.get("class_names", [])] == class_names:
            prototypes = bank.get("prototypes")
            selected_weight = float(bank.get("selected_weight", prototype_cfg.get("weight", 0.25)))
            validated_enabled = bool(bank.get("validated_enabled", selected_weight > 0.0))
            if isinstance(prototypes, torch.Tensor) and validated_enabled and selected_weight > 0.0:
                prototype_tensor = torch.nn.functional.normalize(prototypes.to(device).float(), p=2, dim=1)
                prototype_weight = min(0.5, max(0.0, selected_weight))
                prototype_temperature = max(1e-3, float(bank.get("temperature", prototype_cfg.get("temperature", 0.12))))

    loader = DataLoader(
        test_dataset,
        batch_size=int(config["training"].get("batch_size", 16)),
        shuffle=False,
        num_workers=int(config["training"].get("num_workers", 0)),
    )

    y_true: list[int] = []
    y_pred: list[int] = []
    base_y_pred: list[int] = []
    prediction_rows: list[dict[str, Any]] = []
    top2_hits = 0
    with torch.no_grad():
        for inputs, targets, files in loader:
            inputs_device = inputs.to(device)
            logits = model(inputs_device)
            base_probabilities = torch.softmax(logits, dim=1)
            probabilities = base_probabilities
            if prototype_tensor is not None:
                embeddings = extract_feature_embedding(model, str(payload["architecture"]), inputs_device)
                similarities = embeddings @ prototype_tensor.T
                prototype_probabilities = torch.softmax(similarities / prototype_temperature, dim=1)
                probabilities = (1.0 - prototype_weight) * base_probabilities + prototype_weight * prototype_probabilities
                probabilities = probabilities / probabilities.sum(dim=1, keepdim=True).clamp_min(1e-12)

            probabilities_cpu = probabilities.cpu()
            base_probabilities_cpu = base_probabilities.cpu()
            top_values, top_indices = torch.topk(probabilities_cpu, k=min(2, probabilities_cpu.shape[1]), dim=1)
            base_values, base_indices = torch.topk(base_probabilities_cpu, k=1, dim=1)
            for index in range(len(files)):
                actual_idx = int(targets[index].item())
                predicted_idx = int(top_indices[index, 0].item())
                base_predicted_idx = int(base_indices[index, 0].item())
                second_idx = int(top_indices[index, 1].item()) if top_indices.shape[1] > 1 else predicted_idx
                confidence = float(top_values[index, 0].item())
                second_confidence = float(top_values[index, 1].item()) if top_values.shape[1] > 1 else 0.0
                top2 = [int(v) for v in top_indices[index].tolist()]
                top2_hits += int(actual_idx in top2)
                y_true.append(actual_idx)
                y_pred.append(predicted_idx)
                base_y_pred.append(base_predicted_idx)
                prediction_rows.append({
                    "file": files[index],
                    "actual_class": class_names[actual_idx],
                    "predicted_class": class_names[predicted_idx],
                    "confidence": confidence,
                    "correct": actual_idx == predicted_idx,
                    "second_choice": class_names[second_idx],
                    "second_confidence": second_confidence,
                    "base_predicted_class": class_names[base_predicted_idx],
                    "base_confidence": float(base_values[index, 0].item()),
                    "prototype_assist_used": prototype_tensor is not None,
                    "prototype_weight": prototype_weight if prototype_tensor is not None else 0.0,
                })

    metrics = classification_metrics(y_true, y_pred, class_names)
    metrics["top_2_accuracy"] = float(top2_hits / len(y_true))
    metrics["prototype_assist_used"] = bool(prototype_tensor is not None)
    metrics["prototype_weight"] = float(prototype_weight if prototype_tensor is not None else 0.0)
    base_metrics = classification_metrics(y_true, base_y_pred, class_names)
    matrix = confusion(y_true, y_pred, len(class_names))
    report_text = text_classification_report(y_true, y_pred, class_names)

    reports_dir = Path(config["project"]["reports_dir"]) / "evaluation"
    reports_dir.mkdir(parents=True, exist_ok=True)
    save_json(metrics, reports_dir / "metrics.json")
    save_json(base_metrics, reports_dir / "base_classifier_metrics.json")
    (reports_dir / "classification_report.txt").write_text(report_text, encoding="utf-8")
    pd.DataFrame(prediction_rows).to_csv(reports_dir / "predictions.csv", index=False)
    _plot_confusion_matrix(matrix, class_names, reports_dir / "confusion_matrix.png")

    misclassified = [row for row in prediction_rows if not row["correct"]]
    misclassified_dir = reports_dir / "misclassified"
    misclassified_dir.mkdir(parents=True, exist_ok=True)
    misclassified_rows: list[dict[str, Any]] = []
    pair_counter: Counter[tuple[str, str]] = Counter()
    for row in misclassified:
        source = raw_dir / row["file"]
        pair_dir = misclassified_dir / f"{row['actual_class']}__as__{row['predicted_class']}"
        copied = copy_preserving_name(source, pair_dir)
        pair_counter[(row["actual_class"], row["predicted_class"])] += 1
        misclassified_rows.append({
            "image": row["file"],
            "copied_to": str(copied),
            "true_class": row["actual_class"],
            "predicted_class": row["predicted_class"],
            "confidence": row["confidence"],
            "second_choice": row["second_choice"],
            "second_confidence": row["second_confidence"],
        })
    pd.DataFrame(
        misclassified_rows,
        columns=["image", "copied_to", "true_class", "predicted_class", "confidence", "second_choice", "second_confidence"],
    ).to_csv(reports_dir / "misclassified.csv", index=False)
    confused_pairs = [
        {"true_class": pair[0], "predicted_class": pair[1], "count": count}
        for pair, count in pair_counter.most_common()
    ]
    save_json(confused_pairs, reports_dir / "confused_pairs.json")

    result = {
        "metrics": metrics,
        "base_classifier_metrics": base_metrics,
        "num_test_originals": len(y_true),
        "num_misclassified": len(misclassified),
        "confused_pairs": confused_pairs,
        "model_version": payload.get("model_version"),
    }
    if not quiet:
        print("\nTEST EVALUATION — UNTOUCHED ORIGINALS")
        print("=" * 60)
        print(f"Images: {len(y_true)}")
        print(f"Accuracy: {metrics['accuracy']:.2%}")
        print(f"Macro F1: {metrics['macro_f1']:.2%}")
        print(f"Weighted F1: {metrics['weighted_f1']:.2%}")
        print(f"Top-2 accuracy: {metrics['top_2_accuracy']:.2%}")
        if prototype_tensor is not None:
            print(f"Prototype assist: ON ({prototype_weight:.0%} validation-selected blend)")
            print(f"Base classifier macro F1: {base_metrics['macro_f1']:.2%}")
        else:
            print("Prototype assist: OFF")
        print(f"Misclassified: {len(misclassified)}")
        if confused_pairs:
            print("Most frequent confused pairs:")
            for pair in confused_pairs[:10]:
                print(f"  {pair['true_class']} -> {pair['predicted_class']}: {pair['count']}")
        print(f"Reports: {reports_dir}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a trained artifact on untouched test originals.")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()
    config = load_config(args.config) if args.config else None
    if config:
        configure_logging(config["project"].get("log_level", "INFO"))
    else:
        configure_logging("INFO")
    evaluate_artifact(args.artifact, config=config, manifest_path=args.manifest)


if __name__ == "__main__":
    main()
