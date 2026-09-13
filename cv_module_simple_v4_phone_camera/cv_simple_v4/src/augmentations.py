from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import torch
from PIL import Image, ImageOps
from torchvision import transforms

from src.config import load_config
from src.inspect_dataset import inspect_dataset, validate_dataset_for_training
from src.reproducibility import set_global_seed
from src.utils import configure_logging

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class PadToSquare:
    """Pad without stretching geometry before the network resize."""

    def __init__(self, fill: int | tuple[int, int, int] = 127) -> None:
        self.fill = fill

    def __call__(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        if width == height:
            return image
        side = max(width, height)
        left = (side - width) // 2
        right = side - width - left
        top = (side - height) // 2
        bottom = side - height - top
        return ImageOps.expand(image, border=(left, top, right, bottom), fill=self.fill)


class AddGaussianNoise:
    """Mild sensor-like noise, applied only to training tensors."""

    def __init__(self, std: float = 0.015, p: float = 0.20) -> None:
        self.std = float(std)
        self.p = float(p)

    def __call__(self, tensor: torch.Tensor) -> torch.Tensor:
        if torch.rand(1).item() < self.p:
            tensor = (tensor + torch.randn_like(tensor) * self.std).clamp(0.0, 1.0)
        return tensor


def _geometry_prefix(config: dict[str, Any]) -> list[Any]:
    image_size = int(config["model"]["image_size"])
    preserve_aspect = bool(config.get("preprocessing", {}).get("preserve_aspect_ratio", True))
    fill = int(config.get("preprocessing", {}).get("padding_value", 127))
    operations: list[Any] = []
    if preserve_aspect:
        operations.append(PadToSquare(fill=(fill, fill, fill)))
    operations.append(transforms.Resize((image_size, image_size), antialias=True))
    return operations


def build_train_transform(config: dict[str, Any], normalize: bool = True) -> transforms.Compose:
    """Training-only augmentation tuned for a tiny industrial image dataset.

    The transforms are intentionally stronger than V1 but still preserve the core's
    identity. There are no flips by default because orientation can carry class
    information. Validation/test/inference never use these random transforms.
    """
    aug = config["augmentation"]
    if not aug.get("enabled", True):
        return build_eval_transform(config, normalize=normalize)

    fill = int(config.get("preprocessing", {}).get("padding_value", 127))
    operations: list[Any] = _geometry_prefix(config)
    operations.extend(
        [
            transforms.RandomAffine(
                degrees=float(aug.get("rotation", 14)),
                translate=(float(aug.get("translation", 0.08)),) * 2,
                scale=(float(aug.get("scale_min", 0.90)), float(aug.get("scale_max", 1.10))),
                shear=float(aug.get("shear", 3.0)),
                interpolation=transforms.InterpolationMode.BILINEAR,
                fill=fill,
            ),
            transforms.RandomPerspective(
                distortion_scale=float(aug.get("perspective_distortion", 0.08)),
                p=float(aug.get("perspective_probability", 0.15)),
                interpolation=transforms.InterpolationMode.BILINEAR,
                fill=fill,
            ),
            transforms.ColorJitter(
                brightness=float(aug.get("brightness", 0.18)),
                contrast=float(aug.get("contrast", 0.18)),
                saturation=float(aug.get("saturation", 0.10)),
                hue=float(aug.get("hue", 0.02)),
            ),
            transforms.RandomAutocontrast(p=float(aug.get("autocontrast_probability", 0.15))),
            transforms.RandomAdjustSharpness(
                sharpness_factor=float(aug.get("sharpness_factor", 1.4)),
                p=float(aug.get("sharpness_probability", 0.15)),
            ),
            transforms.RandomApply(
                [
                    transforms.GaussianBlur(
                        kernel_size=int(aug.get("blur_kernel_size", 3)),
                        sigma=(0.1, 1.0),
                    )
                ],
                p=float(aug.get("blur_probability", 0.12)),
            ),
        ]
    )
    if bool(aug.get("horizontal_flip", False)):
        operations.append(
            transforms.RandomHorizontalFlip(p=float(aug.get("horizontal_flip_probability", 0.5)))
        )

    operations.extend(
        [
            transforms.ToTensor(),
            AddGaussianNoise(
                std=float(aug.get("noise_std", 0.015)),
                p=float(aug.get("noise_probability", 0.20)),
            ),
            transforms.RandomErasing(
                p=float(aug.get("random_erasing_probability", 0.10)),
                scale=(
                    float(aug.get("random_erasing_scale_min", 0.01)),
                    float(aug.get("random_erasing_scale_max", 0.04)),
                ),
                ratio=(0.5, 2.0),
                value="random",
            ),
        ]
    )
    if normalize:
        operations.append(transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD))
    return transforms.Compose(operations)


def build_eval_transform(config: dict[str, Any], normalize: bool = True) -> transforms.Compose:
    operations: list[Any] = _geometry_prefix(config)
    operations.append(transforms.ToTensor())
    if normalize:
        operations.append(transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD))
    return transforms.Compose(operations)


def create_augmentation_previews(config: dict[str, Any], variants: int = 8) -> list[Path]:
    report = inspect_dataset(config, write_report=True)
    validate_dataset_for_training(report)
    seed = int(config["dataset"]["seed"])
    set_global_seed(seed)
    rng = random.Random(seed)
    raw_dir = Path(config["dataset"]["raw_dir"])
    output_dir = Path(config["project"]["reports_dir"]) / "augmentation_preview"
    output_dir.mkdir(parents=True, exist_ok=True)
    transform = build_train_transform(config, normalize=False)
    output_paths: list[Path] = []

    by_class: dict[str, list[str]] = {name: [] for name in report["discovered_classes"]}
    for record in report["valid_records"]:
        by_class[record["class"]].append(record["file"])

    for class_name, files in by_class.items():
        if not files:
            continue
        source_rel = rng.choice(files)
        source_path = raw_dir / source_rel
        with Image.open(source_path) as source:
            source = source.convert("RGB")
            cols = 3
            rows = (variants + 1 + cols - 1) // cols
            fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
            flat_axes = list(axes.flat) if hasattr(axes, "flat") else [axes]
            flat_axes[0].imshow(source)
            flat_axes[0].set_title("Original")
            flat_axes[0].axis("off")
            for index in range(variants):
                augmented = transform(source.copy())
                flat_axes[index + 1].imshow(augmented.permute(1, 2, 0).clamp(0, 1))
                flat_axes[index + 1].set_title(f"Aug {index + 1}")
                flat_axes[index + 1].axis("off")
            for axis in flat_axes[variants + 1 :]:
                axis.axis("off")
            fig.suptitle(f"{class_name} - realistic training-only variation")
            fig.tight_layout()
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in class_name)
            destination = output_dir / f"{safe_name}.png"
            fig.savefig(destination, dpi=140, bbox_inches="tight")
            plt.close(fig)
            output_paths.append(destination)
    return output_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview realistic training-only augmentation.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--preview", action="store_true", help="Generate preview grids.")
    parser.add_argument("--variants", type=int, default=8)
    args = parser.parse_args()
    config = load_config(args.config)
    configure_logging(config["project"].get("log_level", "INFO"))
    if not args.preview:
        parser.error("Use --preview to generate augmentation preview grids.")
    paths = create_augmentation_previews(config, variants=args.variants)
    print(f"Created {len(paths)} augmentation preview(s) in reports/augmentation_preview/")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
