from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from src.config import load_config
from src.utils import configure_logging, save_json, sha256_file, verify_image

LOGGER = logging.getLogger(__name__)


def discover_class_dirs(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        return []
    return sorted(path for path in raw_dir.iterdir() if path.is_dir() and not path.name.startswith("."))


def inspect_dataset(config: dict[str, Any], write_report: bool = True) -> dict[str, Any]:
    raw_dir = Path(config["dataset"]["raw_dir"])
    supported = {ext.lower() for ext in config["dataset"]["supported_extensions"]}
    expected = int(config["dataset"].get("expected_num_classes", 5))
    class_dirs = discover_class_dirs(raw_dir)
    class_names = [path.name for path in class_dirs]

    valid_records: list[dict[str, Any]] = []
    invalid_files: list[dict[str, str]] = []
    extension_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    basename_map: defaultdict[str, list[str]] = defaultdict(list)
    hash_map: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    class_counts: Counter[str] = Counter()
    widths: list[int] = []
    heights: list[int] = []

    for class_dir in class_dirs:
        for path in sorted(class_dir.rglob("*")):
            if not path.is_file():
                continue
            extension_counts[path.suffix.lower() or "<none>"] += 1
            if path.suffix.lower() not in supported:
                continue
            relative = str(path.relative_to(raw_dir))
            basename_map[path.name.lower()].append(relative)
            is_valid, error, metadata = verify_image(path)
            if not is_valid or metadata is None:
                invalid_files.append({"file": relative, "error": error or "unknown image error"})
                continue
            digest = sha256_file(path)
            record = {
                "file": relative,
                "class": class_dir.name,
                "sha256": digest,
                **metadata,
            }
            valid_records.append(record)
            hash_map[digest].append({"file": relative, "class": class_dir.name})
            class_counts[class_dir.name] += 1
            widths.append(metadata["width"])
            heights.append(metadata["height"])
            mode_counts[metadata["mode"]] += 1

    duplicate_groups = [items for items in hash_map.values() if len(items) > 1]
    cross_class_duplicates = [
        items for items in duplicate_groups if len({item["class"] for item in items}) > 1
    ]
    duplicate_filenames = {
        name: paths for name, paths in basename_map.items() if len(paths) > 1
    }

    valid_counts = [class_counts.get(name, 0) for name in class_names]
    min_count = min(valid_counts) if valid_counts else 0
    max_count = max(valid_counts) if valid_counts else 0
    imbalance_ratio = (max_count / min_count) if min_count > 0 else None
    min_sensible = int(config["dataset"].get("minimum_sensible_originals_per_class", 10))

    warnings: list[str] = []
    if len(class_names) != expected:
        warnings.append(
            f"Expected exactly {expected} class folders, but discovered {len(class_names)}: {class_names}"
        )
    empty_classes = [name for name in class_names if class_counts.get(name, 0) == 0]
    if empty_classes:
        warnings.append(f"Classes with zero valid images: {empty_classes}")
    if min_count and min_count < min_sensible:
        warnings.append(
            f"Small dataset warning: minimum valid originals in a class is {min_count}; "
            f"configured sensible minimum is {min_sensible}. Consider k-fold evaluation."
        )
    if imbalance_ratio is not None and imbalance_ratio >= float(
        config["training"].get("imbalance_ratio_threshold", 1.5)
    ):
        warnings.append(f"Class imbalance detected: largest/smallest class ratio = {imbalance_ratio:.2f}")
    if invalid_files:
        warnings.append(f"Found {len(invalid_files)} invalid or unreadable image file(s).")
    if duplicate_groups:
        warnings.append(
            f"Found {len(duplicate_groups)} exact duplicate content group(s). "
            "Duplicate hashes will be grouped together during splitting to prevent leakage."
        )
    if cross_class_duplicates:
        warnings.append(
            "CRITICAL: exact duplicate image content exists under different class labels. "
            "Split/training will refuse this contradictory dataset until corrected."
        )

    dimension_stats = None
    if widths and heights:
        dimension_stats = {
            "width": {
                "min": min(widths),
                "max": max(widths),
                "mean": round(mean(widths), 2),
                "median": median(widths),
            },
            "height": {
                "min": min(heights),
                "max": max(heights),
                "mean": round(mean(heights), 2),
                "median": median(heights),
            },
        }

    report: dict[str, Any] = {
        "raw_dir": str(raw_dir),
        "discovered_classes": class_names,
        "num_classes": len(class_names),
        "expected_num_classes": expected,
        "class_counts_valid_originals": {name: class_counts.get(name, 0) for name in class_names},
        "total_valid_images": len(valid_records),
        "extensions_seen": dict(sorted(extension_counts.items())),
        # These lists intentionally overlap: a corrupt image is also unreadable by the CV pipeline.
        "invalid_or_corrupted_files": invalid_files,
        "unreadable_files": invalid_files,
        "invalid_or_unreadable_files": invalid_files,
        "dimension_statistics": dimension_stats,
        "image_modes": dict(sorted(mode_counts.items())),
        "class_imbalance": {
            "min_class_count": min_count,
            "max_class_count": max_count,
            "max_to_min_ratio": round(imbalance_ratio, 4) if imbalance_ratio is not None else None,
        },
        "exact_duplicate_groups": duplicate_groups,
        "cross_class_duplicate_groups": cross_class_duplicates,
        "potential_duplicate_filenames": duplicate_filenames,
        "warnings": warnings,
        "valid_records": valid_records,
    }

    if write_report:
        report_path = Path(config["project"]["reports_dir"]) / "dataset_report.json"
        save_json(report, report_path)

    return report


def print_report(report: dict[str, Any]) -> None:
    print("\nDATASET INSPECTION")
    print("=" * 60)
    print(f"Classes ({report['num_classes']}): {', '.join(report['discovered_classes']) or '<none>'}")
    print(f"Total valid original images: {report['total_valid_images']}")
    print("Per class:")
    for name, count in report["class_counts_valid_originals"].items():
        print(f"  - {name}: {count}")
    print(f"Extensions seen: {report['extensions_seen']}")
    print(f"Image modes: {report['image_modes']}")
    if report["dimension_statistics"]:
        print(f"Dimensions: {report['dimension_statistics']}")
    print(f"Invalid/unreadable: {len(report['invalid_or_unreadable_files'])}")
    print(f"Exact duplicate groups: {len(report['exact_duplicate_groups'])}")
    print(f"Potential duplicate filenames: {len(report['potential_duplicate_filenames'])}")
    if report["warnings"]:
        print("\nWARNINGS:")
        for warning in report["warnings"]:
            print(f"  ! {warning}")
    print("=" * 60)


def validate_dataset_for_training(report: dict[str, Any]) -> None:
    if report["num_classes"] != report["expected_num_classes"]:
        raise ValueError(
            f"Training blocked: expected {report['expected_num_classes']} classes, "
            f"found {report['num_classes']}."
        )
    zero = [name for name, count in report["class_counts_valid_originals"].items() if count == 0]
    if zero:
        raise ValueError(f"Training blocked: classes with zero valid images: {zero}")
    if report["cross_class_duplicate_groups"]:
        raise ValueError(
            "Training blocked: identical image content appears under different class labels. "
            "Correct the dataset first."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the original-image dataset.")
    parser.add_argument("--config", default="configs/default.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    configure_logging(config["project"].get("log_level", "INFO"))
    report = inspect_dataset(config, write_report=True)
    print_report(report)
    report_path = Path(config["project"]["reports_dir"]) / "dataset_report.json"
    print(f"Report saved to: {report_path}")
    if report["num_classes"] != report["expected_num_classes"] or report["cross_class_duplicate_groups"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
