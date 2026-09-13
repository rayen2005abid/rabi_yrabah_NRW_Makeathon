from __future__ import annotations

from pathlib import Path

import pytest
import torch
import yaml
from PIL import Image

from src.config import save_config_snapshot
from src.models import build_model
from src.utils import save_json


@pytest.fixture
def base_config(tmp_path: Path) -> dict:
    config = {
        "project": {
            "model_version": "core_classifier_test",
            "artifact_dir": str(tmp_path / "artifacts" / "core_classifier_test"),
            "reports_dir": str(tmp_path / "reports"),
            "log_level": "INFO",
        },
        "dataset": {
            "raw_dir": str(tmp_path / "data" / "raw"),
            "expected_num_classes": 5,
            "train_ratio": 0.70,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
            "seed": 42,
            "evaluation_mode": "split",
            "kfold_folds": 5,
            "fold_index": 0,
            "split_manifest": str(tmp_path / "reports" / "splits" / "split_manifest.csv"),
            "kfold_dir": str(tmp_path / "reports" / "splits" / "kfold"),
            "supported_extensions": [".jpg", ".jpeg", ".png"],
            "minimum_sensible_originals_per_class": 10,
        },
        "augmentation": {
            "enabled": True,
            "rotation": 12,
            "translation": 0.08,
            "scale_min": 0.90,
            "scale_max": 1.10,
            "crop_scale_min": 0.90,
            "crop_scale_max": 1.00,
            "brightness": 0.15,
            "contrast": 0.15,
            "saturation": 0.10,
            "blur_probability": 0.15,
            "blur_kernel_size": 3,
            "noise_probability": 0.15,
            "noise_std": 0.015,
            "perspective_probability": 0.10,
            "perspective_distortion": 0.08,
            "horizontal_flip": False,
            "horizontal_flip_probability": 0.5,
        },
        "model": {"architecture": "resnet18", "pretrained": False, "image_size": 64, "dropout": 0.10},
        "training": {
            "batch_size": 2,
            "epochs_head": 1,
            "epochs_finetune": 0,
            "lr_head": 0.001,
            "lr_finetune": 0.0001,
            "weight_decay": 0.0001,
            "patience": 2,
            "num_workers": 0,
            "finetune": False,
            "finetune_fraction": 0.30,
            "scheduler_factor": 0.5,
            "scheduler_patience": 1,
            "class_weighting": "auto",
            "imbalance_ratio_threshold": 1.5,
            "weighted_sampler": False,
            "checkpoint_every_epoch": False,
        },
        "inference": {"accept_threshold": 0.80, "review_threshold": 0.60, "top_k": 5, "max_upload_mb": 2},
    }
    Path(config["dataset"]["raw_dir"]).mkdir(parents=True, exist_ok=True)
    return config


@pytest.fixture
def dummy_artifact(tmp_path: Path, base_config: dict) -> Path:
    artifact = Path(base_config["project"]["artifact_dir"])
    artifact.mkdir(parents=True, exist_ok=True)
    classes = [f"CORE_{letter}" for letter in "ABCDE"]
    mapping = {name: index for index, name in enumerate(classes)}
    model = build_model("resnet18", num_classes=5, pretrained=False, dropout=0.10)
    payload = {
        "model_state_dict": model.state_dict(),
        "architecture": "resnet18",
        "num_classes": 5,
        "classes": classes,
        "image_size": 64,
        "dropout": 0.10,
        "model_version": "core_classifier_test",
        "thresholds": {"accept_threshold": 0.80, "review_threshold": 0.60},
    }
    torch.save(payload, artifact / "model.pt")
    save_json(mapping, artifact / "class_mapping.json")
    save_json(
        {
            "model_version": "core_classifier_test",
            "architecture": "resnet18",
            "classes": classes,
            "num_classes": 5,
            "image_size": 64,
            "thresholds": payload["thresholds"],
        },
        artifact / "metadata.json",
    )
    save_config_snapshot(base_config, artifact / "config_snapshot.yaml")
    return artifact


def make_image(path: Path, value: int = 128, size: tuple[int, int] = (80, 60)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(value, max(0, value - 20), min(255, value + 20))).save(path)
