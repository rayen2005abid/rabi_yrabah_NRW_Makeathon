from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path("configs/default.yaml")


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Load and minimally validate a YAML configuration file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    required_sections = {"project", "dataset", "augmentation", "model", "training", "inference"}
    missing = required_sections.difference(config)
    if missing:
        raise ValueError(f"Missing required config sections: {sorted(missing)}")

    ratios = [
        float(config["dataset"]["train_ratio"]),
        float(config["dataset"]["val_ratio"]),
        float(config["dataset"]["test_ratio"]),
    ]
    if any(r <= 0 for r in ratios) or abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError("dataset train/val/test ratios must be positive and sum to 1.0")

    accept = float(config["inference"]["accept_threshold"])
    review = float(config["inference"]["review_threshold"])
    if not (0 <= review <= accept <= 1):
        raise ValueError("Thresholds must satisfy 0 <= review_threshold <= accept_threshold <= 1")
    return config


def save_config_snapshot(config: dict[str, Any], destination: str | Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(copy.deepcopy(config), handle, sort_keys=False)


def resolve_path(value: str | Path, project_root: str | Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    root = Path(project_root) if project_root else Path.cwd()
    return (root / path).resolve()
