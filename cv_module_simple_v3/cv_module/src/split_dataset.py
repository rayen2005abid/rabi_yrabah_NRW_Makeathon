from __future__ import annotations

import argparse
import logging
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import load_config
from src.inspect_dataset import inspect_dataset, validate_dataset_for_training
from src.reproducibility import set_global_seed
from src.utils import configure_logging, save_json

LOGGER = logging.getLogger(__name__)


def _hash_groups(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in report["valid_records"]:
        groups[record["sha256"]].append(record)
    return dict(groups)


def _allocate_counts(n: int, train_ratio: float, val_ratio: float, test_ratio: float) -> tuple[int, int, int]:
    """Allocate original-image groups while preserving train data and evaluation when feasible."""
    if n <= 0:
        return 0, 0, 0
    if n == 1:
        return 1, 0, 0
    if n == 2:
        return 1, 0, 1

    n_val = max(1, int(round(n * val_ratio)))
    n_test = max(1, int(round(n * test_ratio)))
    while n_val + n_test > n - 1:
        if n_val >= n_test and n_val > 1:
            n_val -= 1
        elif n_test > 1:
            n_test -= 1
        else:
            break
    n_train = n - n_val - n_test
    return n_train, n_val, n_test


def create_split_manifest(config: dict[str, Any], report: dict[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    report = report or inspect_dataset(config, write_report=True)
    validate_dataset_for_training(report)
    seed = int(config["dataset"]["seed"])
    set_global_seed(seed)
    rng = random.Random(seed)
    groups = _hash_groups(report)
    by_class: defaultdict[str, list[str]] = defaultdict(list)
    for digest, items in groups.items():
        labels = {item["class"] for item in items}
        if len(labels) != 1:
            raise ValueError(f"Cross-class duplicate hash cannot be split safely: {digest}")
        by_class[next(iter(labels))].append(digest)

    tr = float(config["dataset"]["train_ratio"])
    vr = float(config["dataset"]["val_ratio"])
    ter = float(config["dataset"]["test_ratio"])
    group_split: dict[str, str] = {}
    warnings: list[str] = []

    for class_name in sorted(by_class):
        class_groups = sorted(by_class[class_name])
        rng.shuffle(class_groups)
        n_train, n_val, n_test = _allocate_counts(len(class_groups), tr, vr, ter)
        if len(class_groups) < 7:
            warnings.append(
                f"{class_name}: only {len(class_groups)} unique original image group(s); "
                f"safe split is train={n_train}, val={n_val}, test={n_test}."
            )
        for digest in class_groups[:n_train]:
            group_split[digest] = "train"
        for digest in class_groups[n_train:n_train + n_val]:
            group_split[digest] = "val"
        for digest in class_groups[n_train + n_val:n_train + n_val + n_test]:
            group_split[digest] = "test"

    rows: list[dict[str, Any]] = []
    for digest, items in groups.items():
        split = group_split[digest]
        for item in items:
            rows.append({"file": item["file"], "class": item["class"], "sha256": digest, "split": split})
    frame = pd.DataFrame(rows).sort_values(["split", "class", "file"]).reset_index(drop=True)

    counts = frame.groupby(["split", "class"]).size().unstack(fill_value=0).to_dict(orient="index")
    split_totals = frame["split"].value_counts().to_dict()
    if split_totals.get("val", 0) == 0 or split_totals.get("test", 0) == 0:
        warnings.append(
            "At least one evaluation split is empty because the dataset is too small. "
            "Training with early stopping requires non-empty validation and test originals."
        )

    summary = {
        "evaluation_mode": "split",
        "seed": seed,
        "duplicate_safety": "All files sharing an exact SHA-256 hash are kept in the same split.",
        "split_totals": split_totals,
        "per_split_class_counts": counts,
        "warnings": warnings,
    }
    manifest_path = Path(config["dataset"]["split_manifest"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(manifest_path, index=False)
    save_json(summary, manifest_path.with_suffix(".json"))
    return frame, summary


def create_kfold_manifests(config: dict[str, Any], report: dict[str, Any] | None = None) -> tuple[list[Path], dict[str, Any]]:
    """Create group-safe stratified folds.

    Each fold uses one bucket as untouched test data and the next bucket as validation data;
    all other buckets form training data. Augmentation remains training-only.
    """
    report = report or inspect_dataset(config, write_report=True)
    validate_dataset_for_training(report)
    seed = int(config["dataset"]["seed"])
    set_global_seed(seed)
    rng = random.Random(seed)
    groups = _hash_groups(report)
    by_class: defaultdict[str, list[str]] = defaultdict(list)
    for digest, items in groups.items():
        label = {item["class"] for item in items}
        if len(label) != 1:
            raise ValueError("Cross-class exact duplicates must be fixed before k-fold splitting.")
        by_class[next(iter(label))].append(digest)

    requested = int(config["dataset"].get("kfold_folds", 5))
    minimum_unique = min((len(v) for v in by_class.values()), default=0)
    n_folds = min(requested, minimum_unique)
    if n_folds < 3:
        raise ValueError(
            "K-fold mode requires at least 3 unique original-image hash groups per class "
            "so train, validation, and test remain separate."
        )

    assignments: dict[str, int] = {}
    for class_name, digests in sorted(by_class.items()):
        digests = sorted(digests)
        rng.shuffle(digests)
        for index, digest in enumerate(digests):
            assignments[digest] = index % n_folds

    output_dir = Path(config["dataset"]["kfold_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    fold_summaries: list[dict[str, Any]] = []
    for fold in range(n_folds):
        val_fold = (fold + 1) % n_folds
        rows: list[dict[str, Any]] = []
        for digest, items in groups.items():
            bucket = assignments[digest]
            split = "test" if bucket == fold else "val" if bucket == val_fold else "train"
            for item in items:
                rows.append({"file": item["file"], "class": item["class"], "sha256": digest, "split": split})
        frame = pd.DataFrame(rows).sort_values(["split", "class", "file"]).reset_index(drop=True)
        path = output_dir / f"fold_{fold}.csv"
        frame.to_csv(path, index=False)
        paths.append(path)
        fold_summaries.append({
            "fold": fold,
            "validation_bucket": val_fold,
            "totals": frame["split"].value_counts().to_dict(),
        })

    summary = {
        "evaluation_mode": "kfold",
        "requested_folds": requested,
        "actual_folds": n_folds,
        "seed": seed,
        "duplicate_safety": "Exact duplicate hashes are assigned as indivisible groups.",
        "folds": fold_summaries,
        "warning": (
            f"Fold count reduced from {requested} to {n_folds} because the smallest class has "
            f"{minimum_unique} unique original-image groups."
            if n_folds < requested else None
        ),
    }
    save_json(summary, output_dir / "kfold_summary.json")
    return paths, summary


def ensure_manifest(config: dict[str, Any], evaluation_mode: str | None = None, fold: int | None = None) -> Path:
    mode = evaluation_mode or str(config["dataset"].get("evaluation_mode", "split"))
    if mode == "split":
        path = Path(config["dataset"]["split_manifest"])
        if not path.exists():
            create_split_manifest(config)
        return path
    if mode == "kfold":
        fold_index = int(config["dataset"].get("fold_index", 0) if fold is None else fold)
        path = Path(config["dataset"]["kfold_dir"]) / f"fold_{fold_index}.csv"
        if not path.exists():
            paths, _ = create_kfold_manifests(config)
            if fold_index >= len(paths):
                raise ValueError(f"Requested fold {fold_index}, but only {len(paths)} folds are feasible.")
        return path
    raise ValueError("evaluation_mode must be 'split' or 'kfold'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create leakage-safe original-image dataset splits.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--evaluation-mode", choices=["split", "kfold"], default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    configure_logging(config["project"].get("log_level", "INFO"))
    mode = args.evaluation_mode or config["dataset"].get("evaluation_mode", "split")
    report = inspect_dataset(config, write_report=True)
    if mode == "split":
        frame, summary = create_split_manifest(config, report)
        print(frame.groupby(["split", "class"]).size().unstack(fill_value=0))
        for warning in summary["warnings"]:
            LOGGER.warning(warning)
        print(f"\nSaved split manifest: {config['dataset']['split_manifest']}")
    else:
        paths, summary = create_kfold_manifests(config, report)
        if summary.get("warning"):
            LOGGER.warning(summary["warning"])
        print(f"Created {len(paths)} folds under: {config['dataset']['kfold_dir']}")


if __name__ == "__main__":
    main()
