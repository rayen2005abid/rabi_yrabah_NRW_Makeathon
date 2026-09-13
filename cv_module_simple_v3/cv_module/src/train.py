from __future__ import annotations

import argparse
import copy
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, f1_score
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, WeightedRandomSampler

from src.augmentations import build_eval_transform, build_train_transform
from src.config import load_config, save_config_snapshot
from src.dataset import CoreImageDataset
from src.inspect_dataset import inspect_dataset, validate_dataset_for_training
from src.models import build_model, freeze_backbone, unfreeze_final_backbone_fraction
from src.reproducibility import set_global_seed
from src.split_dataset import ensure_manifest
from src.utils import configure_logging, save_json, utc_now_iso

LOGGER = logging.getLogger(__name__)


def select_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _make_loader(
    dataset: CoreImageDataset,
    batch_size: int,
    shuffle: bool,
    num_workers: int,
    seed: int,
    sampler: WeightedRandomSampler | None = None,
) -> DataLoader:
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle if sampler is None else False,
        sampler=sampler,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
        generator=generator,
    )


def _class_weight_tensor(
    dataset: CoreImageDataset,
    class_names: list[str],
    mode: str,
    imbalance_ratio_threshold: float,
    weight_mode: str,
    effective_num_beta: float,
    device: torch.device,
) -> tuple[torch.Tensor | None, dict[str, float] | None]:
    counts = dataset.class_counts
    values = np.array([counts.get(name, 0) for name in class_names], dtype=float)
    if np.any(values <= 0):
        raise ValueError("Every class must have at least one training original.")

    ratio = float(values.max() / values.min())
    use_weights = mode == "always" or (mode == "auto" and ratio >= imbalance_ratio_threshold)
    if mode == "never" or not use_weights:
        return None, None

    if weight_mode == "effective_num":
        beta = min(0.9999, max(0.0, float(effective_num_beta)))
        if beta == 0.0:
            weights = np.ones_like(values)
        else:
            effective_num = 1.0 - np.power(beta, values)
            weights = (1.0 - beta) / np.maximum(effective_num, 1e-12)
    else:
        weights = values.sum() / (len(values) * values)

    weights = weights / weights.mean()
    mapping = {name: float(weights[index]) for index, name in enumerate(class_names)}
    return torch.tensor(weights, dtype=torch.float32, device=device), mapping


def _weighted_sampler(dataset: CoreImageDataset, class_names: list[str]) -> WeightedRandomSampler:
    counts = dataset.class_counts
    class_weights = {name: 1.0 / counts[name] for name in class_names}
    sample_weights = [class_weights[label] for label in dataset.frame["class"].tolist()]
    return WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)


def _freeze_nontrainable_batchnorm_stats(model: nn.Module) -> None:
    """Do not update BatchNorm running stats in frozen backbone blocks.

    With only a few dozen originals, allowing frozen layers to update their running
    statistics from tiny batches can badly damage the pretrained representation.
    """
    for module in model.modules():
        if isinstance(module, nn.modules.batchnorm._BatchNorm):
            params = list(module.parameters(recurse=False))
            if params and not any(parameter.requires_grad for parameter in params):
                module.eval()


def _run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None,
    gradient_clip_norm: float = 0.0,
) -> dict[str, float]:
    training = optimizer is not None
    model.train(training)
    if training:
        _freeze_nontrainable_batchnorm_stats(model)

    total_loss = 0.0
    all_true: list[int] = []
    all_pred: list[int] = []
    context = torch.enable_grad() if training else torch.no_grad()

    with context:
        for inputs, targets, _ in loader:
            inputs = inputs.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            if training:
                optimizer.zero_grad(set_to_none=True)
            logits = model(inputs)
            loss = criterion(logits, targets)
            if training:
                loss.backward()
                if gradient_clip_norm > 0:
                    torch.nn.utils.clip_grad_norm_(
                        [p for p in model.parameters() if p.requires_grad],
                        max_norm=gradient_clip_norm,
                    )
                optimizer.step()

            total_loss += loss.item() * inputs.size(0)
            predictions = logits.argmax(dim=1)
            all_true.extend(targets.detach().cpu().tolist())
            all_pred.extend(predictions.detach().cpu().tolist())

    samples = max(1, len(loader.dataset))
    return {
        "loss": total_loss / samples,
        "accuracy": float(accuracy_score(all_true, all_pred)),
        "macro_f1": float(f1_score(all_true, all_pred, average="macro", zero_division=0)),
    }


def _train_stage(
    stage_name: str,
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    lr: float,
    weight_decay: float,
    epochs: int,
    patience: int,
    scheduler_factor: float,
    scheduler_patience: int,
    gradient_clip_norm: float,
    best_score: float,
    best_state: dict[str, torch.Tensor] | None,
    history: list[dict[str, Any]],
    checkpoint_dir: Path,
    checkpoint_every_epoch: bool,
) -> tuple[float, dict[str, torch.Tensor], int]:
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = AdamW(trainable, lr=lr, weight_decay=weight_decay)
    scheduler = ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=scheduler_factor,
        patience=scheduler_patience,
    )
    no_improvement = 0
    epochs_run = 0

    for epoch in range(1, epochs + 1):
        train_metrics = _run_epoch(
            model, train_loader, criterion, device, optimizer, gradient_clip_norm
        )
        val_metrics = _run_epoch(model, val_loader, criterion, device, optimizer=None)
        scheduler.step(val_metrics["macro_f1"])
        epochs_run += 1
        record = {
            "stage": stage_name,
            "epoch": epoch,
            "learning_rate": float(optimizer.param_groups[0]["lr"]),
            "train": train_metrics,
            "validation": val_metrics,
        }
        history.append(record)
        LOGGER.info(
            "%s epoch %d/%d | train loss %.4f acc %.4f f1 %.4f | val loss %.4f acc %.4f f1 %.4f",
            stage_name,
            epoch,
            epochs,
            train_metrics["loss"],
            train_metrics["accuracy"],
            train_metrics["macro_f1"],
            val_metrics["loss"],
            val_metrics["accuracy"],
            val_metrics["macro_f1"],
        )

        score = val_metrics["macro_f1"]
        if score > best_score + 1e-8:
            best_score = score
            best_state = copy.deepcopy(model.state_dict())
            no_improvement = 0
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            torch.save(
                {
                    "stage": stage_name,
                    "epoch": epoch,
                    "validation_macro_f1": best_score,
                    "model_state_dict": best_state,
                },
                checkpoint_dir / "best.pt",
            )
        else:
            no_improvement += 1

        if checkpoint_every_epoch:
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            torch.save(
                {"stage": stage_name, "epoch": epoch, "model_state_dict": model.state_dict()},
                checkpoint_dir / f"{stage_name}_epoch_{epoch:03d}.pt",
            )
        if no_improvement >= patience:
            LOGGER.info(
                "Early stopping %s after %d epoch(s) without validation macro-F1 improvement.",
                stage_name,
                patience,
            )
            break

    if best_state is None:
        best_state = copy.deepcopy(model.state_dict())
    return best_score, best_state, epochs_run


def train(config: dict[str, Any], evaluation_mode: str | None = None, fold: int | None = None) -> Path:
    seed = int(config["dataset"]["seed"])
    set_global_seed(seed)
    report = inspect_dataset(config, write_report=True)
    validate_dataset_for_training(report)

    mode = evaluation_mode or str(config["dataset"].get("evaluation_mode", "split"))
    fold_index = int(config["dataset"].get("fold_index", 0) if fold is None else fold)
    manifest_path = ensure_manifest(config, evaluation_mode=mode, fold=fold_index)
    manifest = pd.read_csv(manifest_path)
    split_counts = manifest["split"].value_counts().to_dict()
    if split_counts.get("train", 0) == 0 or split_counts.get("val", 0) == 0 or split_counts.get("test", 0) == 0:
        raise ValueError(
            f"Training requires non-empty train/val/test original-image splits; got {split_counts}. "
            "Collect more original photographs or use a feasible k-fold configuration."
        )

    class_names = sorted(manifest["class"].unique().tolist())
    expected = int(config["dataset"].get("expected_num_classes", 5))
    if len(class_names) != expected:
        raise ValueError(f"Expected {expected} classes in manifest, found {len(class_names)}: {class_names}")
    class_to_idx = {name: index for index, name in enumerate(class_names)}

    raw_dir = Path(config["dataset"]["raw_dir"])
    train_dataset = CoreImageDataset(raw_dir, manifest, "train", build_train_transform(config), class_to_idx)
    val_dataset = CoreImageDataset(raw_dir, manifest, "val", build_eval_transform(config), class_to_idx)
    test_dataset = CoreImageDataset(raw_dir, manifest, "test", build_eval_transform(config), class_to_idx)

    training_cfg = config["training"]
    device = select_device()
    LOGGER.info("Selected device: %s", device)
    LOGGER.info("Class mapping: %s", class_to_idx)
    LOGGER.info(
        "Original-image counts | train=%d val=%d test=%d",
        len(train_dataset), len(val_dataset), len(test_dataset),
    )

    sampler = None
    if bool(training_cfg.get("weighted_sampler", False)):
        sampler = _weighted_sampler(train_dataset, class_names)
        LOGGER.info("WeightedRandomSampler enabled for training only.")

    train_loader = _make_loader(
        train_dataset,
        int(training_cfg["batch_size"]),
        shuffle=True,
        num_workers=int(training_cfg["num_workers"]),
        seed=seed,
        sampler=sampler,
    )
    val_loader = _make_loader(
        val_dataset,
        int(training_cfg["batch_size"]),
        shuffle=False,
        num_workers=int(training_cfg["num_workers"]),
        seed=seed,
    )

    architecture = str(config["model"]["architecture"]).lower()
    model = build_model(
        architecture=architecture,
        num_classes=len(class_names),
        pretrained=bool(config["model"].get("pretrained", True)),
        dropout=float(config["model"].get("dropout", 0.2)),
    ).to(device)

    class_weights, class_weight_mapping = _class_weight_tensor(
        train_dataset,
        class_names,
        mode=str(training_cfg.get("class_weighting", "auto")),
        imbalance_ratio_threshold=float(training_cfg.get("imbalance_ratio_threshold", 1.5)),
        weight_mode=str(training_cfg.get("class_weight_mode", "inverse_frequency")),
        effective_num_beta=float(training_cfg.get("effective_num_beta", 0.95)),
        device=device,
    )
    if sampler is not None and class_weights is not None:
        LOGGER.warning("Weighted sampler enabled; weighted loss disabled to avoid double correction.")
        class_weights = None
        class_weight_mapping = None
    if class_weight_mapping:
        LOGGER.info("Class-weighted loss enabled: %s", class_weight_mapping)

    criterion = nn.CrossEntropyLoss(
        weight=class_weights,
        label_smoothing=float(training_cfg.get("label_smoothing", 0.0)),
    )

    artifact_dir = Path(config["project"]["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = artifact_dir / "checkpoints"
    history: list[dict[str, Any]] = []
    best_score = -1.0
    best_state: dict[str, torch.Tensor] | None = None
    gradient_clip_norm = float(training_cfg.get("gradient_clip_norm", 0.0))

    freeze_backbone(model, architecture)
    best_score, best_state, head_epochs = _train_stage(
        "head", model, train_loader, val_loader, criterion, device,
        lr=float(training_cfg["lr_head"]),
        weight_decay=float(training_cfg["weight_decay"]),
        epochs=int(training_cfg["epochs_head"]),
        patience=int(training_cfg["patience"]),
        scheduler_factor=float(training_cfg.get("scheduler_factor", 0.5)),
        scheduler_patience=int(training_cfg.get("scheduler_patience", 2)),
        gradient_clip_norm=gradient_clip_norm,
        best_score=best_score,
        best_state=best_state,
        history=history,
        checkpoint_dir=checkpoint_dir,
        checkpoint_every_epoch=bool(training_cfg.get("checkpoint_every_epoch", False)),
    )
    model.load_state_dict(best_state)

    finetune_epochs = 0
    if bool(training_cfg.get("finetune", True)) and int(training_cfg.get("epochs_finetune", 0)) > 0:
        unfreeze_final_backbone_fraction(
            model,
            architecture,
            fraction=float(training_cfg.get("finetune_fraction", 0.55)),
        )
        best_score, best_state, finetune_epochs = _train_stage(
            "finetune", model, train_loader, val_loader, criterion, device,
            lr=float(training_cfg["lr_finetune"]),
            weight_decay=float(training_cfg["weight_decay"]),
            epochs=int(training_cfg["epochs_finetune"]),
            patience=int(training_cfg["patience"]),
            scheduler_factor=float(training_cfg.get("scheduler_factor", 0.5)),
            scheduler_patience=int(training_cfg.get("scheduler_patience", 2)),
            gradient_clip_norm=gradient_clip_norm,
            best_score=best_score,
            best_state=best_state,
            history=history,
            checkpoint_dir=checkpoint_dir,
            checkpoint_every_epoch=bool(training_cfg.get("checkpoint_every_epoch", False)),
        )
        model.load_state_dict(best_state)

    best_record = max(history, key=lambda item: item["validation"]["macro_f1"])
    model_version = str(config["project"]["model_version"])
    thresholds = {
        "accept_threshold": float(config["inference"]["accept_threshold"]),
        "review_threshold": float(config["inference"]["review_threshold"]),
    }
    model_payload = {
        "model_state_dict": model.state_dict(),
        "architecture": architecture,
        "num_classes": len(class_names),
        "classes": class_names,
        "image_size": int(config["model"]["image_size"]),
        "dropout": float(config["model"].get("dropout", 0.2)),
        "model_version": model_version,
        "thresholds": thresholds,
    }
    torch.save(model_payload, artifact_dir / "model.pt")
    save_json(class_to_idx, artifact_dir / "class_mapping.json")
    save_json(history, artifact_dir / "training_history.json")
    save_config_snapshot(config, artifact_dir / "config_snapshot.yaml")

    dataset_summary = {
        "total_valid_originals": int(report["total_valid_images"]),
        "per_class_originals": report["class_counts_valid_originals"],
        "split_originals": {key: int(value) for key, value in split_counts.items()},
        "evaluation_mode": mode,
        "fold_index": fold_index if mode == "kfold" else None,
        "manifest": str(manifest_path),
    }
    metadata = {
        "model_version": model_version,
        "architecture": architecture,
        "classes": class_names,
        "num_classes": len(class_names),
        "image_size": int(config["model"]["image_size"]),
        "training_date": utc_now_iso(),
        "seed": seed,
        "dataset_summary": dataset_summary,
        "validation_best": best_record["validation"],
        "training": {
            "head_epochs_run": head_epochs,
            "finetune_epochs_run": finetune_epochs,
            "class_weights": class_weight_mapping,
            "class_weight_mode": training_cfg.get("class_weight_mode"),
            "label_smoothing": float(training_cfg.get("label_smoothing", 0.0)),
            "weighted_sampler": bool(training_cfg.get("weighted_sampler", False)),
        },
        "thresholds": thresholds,
        "metrics": {"validation": best_record["validation"], "test": None},
    }
    save_json(metadata, artifact_dir / "metadata.json")

    from src.feature_prototypes import build_feature_prototypes

    prototype_path = build_feature_prototypes(artifact_dir, config=config, manifest_path=manifest_path)
    prototype_bank = torch.load(prototype_path, map_location="cpu", weights_only=False)
    metadata["prototype_assist"] = {
        "artifact": str(prototype_path),
        "source_split": "train",
        "weight_selection_split": prototype_bank.get("weight_selection_split"),
        "configured_enabled": bool(config.get("inference", {}).get("prototype_assist", {}).get("enabled", True)),
        "validated_enabled": bool(prototype_bank.get("validated_enabled", False)),
        "configured_weight": float(prototype_bank.get("configured_weight", 0.20)),
        "selected_weight": float(prototype_bank.get("selected_weight", 0.0)),
        "validation_scores_by_weight": prototype_bank.get("validation_scores_by_weight", {}),
    }
    save_json(metadata, artifact_dir / "metadata.json")

    from src.evaluate import evaluate_artifact

    evaluation = evaluate_artifact(artifact_dir, config=config, manifest_path=manifest_path, quiet=True)
    metadata["metrics"]["test"] = evaluation["metrics"]
    save_json(metadata, artifact_dir / "metadata.json")

    print("\nTRAINING COMPLETE")
    print("=" * 60)
    print(f"Model: {architecture}")
    print(f"Classes: {len(class_names)}")
    print(f"Original images: {report['total_valid_images']}")
    print(f"Train: {len(train_dataset)}")
    print(f"Validation: {len(val_dataset)}")
    print(f"Test: {len(test_dataset)}")
    print(
        f"Best validation: Accuracy = {best_record['validation']['accuracy']:.2%}, "
        f"Macro F1 = {best_record['validation']['macro_f1']:.2%}"
    )
    print(
        f"Test: Accuracy = {evaluation['metrics']['accuracy']:.2%}, "
        f"Macro F1 = {evaluation['metrics']['macro_f1']:.2%}"
    )
    print(f"Model: {artifact_dir / 'model.pt'}")
    print(
        f"Confusion matrix: {Path(config['project']['reports_dir']) / 'evaluation' / 'confusion_matrix.png'}"
    )
    return artifact_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the robust Smart Core Warehouse classifier.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--evaluation-mode", choices=["split", "kfold"], default=None)
    parser.add_argument("--fold", type=int, default=None, help="K-fold index when evaluation mode is kfold.")
    args = parser.parse_args()
    config = load_config(args.config)
    configure_logging(config["project"].get("log_level", "INFO"))
    train(config, evaluation_mode=args.evaluation_mode, fold=args.fold)


if __name__ == "__main__":
    main()
