from pathlib import Path

import pandas as pd

from src.augmentations import build_eval_transform
from src.dataset import CoreImageDataset
from src.inspect_dataset import inspect_dataset
from src.split_dataset import create_split_manifest
from tests.conftest import make_image


def test_dataset_discovery_and_invalid_handling(base_config: dict) -> None:
    raw = Path(base_config["dataset"]["raw_dir"])
    for index, name in enumerate(["A", "B", "C", "D", "E"]):
        make_image(raw / name / "valid.jpg", value=50 + index * 20)
    (raw / "A" / "broken.jpg").write_bytes(b"this is not a valid image")

    report = inspect_dataset(base_config, write_report=False)
    assert report["num_classes"] == 5
    assert report["total_valid_images"] == 5
    assert len(report["invalid_or_unreadable_files"]) == 1
    assert set(report["discovered_classes"]) == {"A", "B", "C", "D", "E"}


def test_duplicate_hashes_never_cross_splits(base_config: dict) -> None:
    raw = Path(base_config["dataset"]["raw_dir"])
    for class_index, name in enumerate(["A", "B", "C", "D", "E"]):
        for image_index in range(6):
            make_image(raw / name / f"img_{image_index}.png", value=20 + class_index * 35 + image_index)
    # Exact duplicate with a different filename in the same class.
    duplicate_bytes = (raw / "A" / "img_0.png").read_bytes()
    (raw / "A" / "copy_of_img_0.png").write_bytes(duplicate_bytes)

    report = inspect_dataset(base_config, write_report=False)
    frame, _ = create_split_manifest(base_config, report)
    grouped = frame.groupby("sha256")["split"].nunique()
    assert grouped.max() == 1
    assert {"train", "val", "test"}.issubset(set(frame["split"]))


def test_eval_preprocessing_and_dataset_item(base_config: dict) -> None:
    raw = Path(base_config["dataset"]["raw_dir"])
    make_image(raw / "A" / "one.jpg")
    frame = pd.DataFrame([{"file": "A/one.jpg", "class": "A", "sha256": "x", "split": "test"}])
    dataset = CoreImageDataset(raw, frame, "test", build_eval_transform(base_config), {"A": 0})
    tensor, label, file_name = dataset[0]
    assert tensor.shape == (3, 64, 64)
    assert label == 0
    assert file_name == "A/one.jpg"
