from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import pandas as pd
from PIL import Image

from src.explainability import draw_salient_regions, green_attention_overlay, salient_regions
from src.inference import CoreClassifier
from src.utils import load_json


def _pil_to_bgr(image: Image.Image):
    rgb = image.convert("RGB")
    return cv2.cvtColor(__import__("numpy").array(rgb), cv2.COLOR_RGB2BGR)


def generate_class_detail_report(
    artifact_dir: str | Path,
    max_images_per_class: int = 4,
    attention_threshold: float = 0.62,
) -> Path:
    """Generate green model-attention examples for each known type using TRAIN originals only.

    This report does not claim to discover human-named engineering features. It shows
    the image regions the trained CNN currently uses as evidence for each class, so
    the operator can verify whether the network is focusing on real geometry/details
    rather than background, table texture, or lighting artifacts.
    """
    artifact_dir = Path(artifact_dir)
    classifier = CoreClassifier(artifact_dir)
    metadata = load_json(artifact_dir / "metadata.json")
    manifest_path = metadata.get("dataset_summary", {}).get("manifest")
    if not manifest_path:
        manifest_path = classifier.config["dataset"].get("split_manifest")
    manifest = pd.read_csv(manifest_path)
    train = manifest[manifest["split"] == "train"].copy()
    raw_dir = Path(classifier.config["dataset"]["raw_dir"])
    reports_dir = Path(classifier.config["project"]["reports_dir"]) / "class_details"
    reports_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "model_version": classifier.model_version,
        "note": (
            "Green regions are Grad-CAM evidence regions learned by the CNN. "
            "They are diagnostics, not guaranteed physical/engineering feature labels."
        ),
        "classes": {},
    }

    for class_name in classifier.class_names:
        rows = train[train["class"] == class_name].head(max(1, int(max_images_per_class)))
        class_dir = reports_dir / "".join(c if c.isalnum() or c in "-_" else "_" for c in class_name)
        class_dir.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        for _, row in rows.iterrows():
            source = raw_dir / str(row["file"])
            with Image.open(source) as image:
                pil = image.convert("RGB")
                attention, explained_class = classifier.explain_pil(pil, class_name=class_name)
                bgr = _pil_to_bgr(pil)
            regions = salient_regions(
                attention,
                image_width=bgr.shape[1],
                image_height=bgr.shape[0],
                threshold=attention_threshold,
                max_regions=3,
            )
            visual = green_attention_overlay(bgr, attention, threshold=max(0.0, attention_threshold - 0.07))
            visual = draw_salient_regions(visual, regions)
            cv2.putText(
                visual,
                f"TYPE: {class_name} | green = learned evidence",
                (18, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (40, 235, 40),
                2,
                cv2.LINE_AA,
            )
            destination = class_dir / f"{source.stem}_details.jpg"
            cv2.imwrite(str(destination), visual)
            entries.append(
                {
                    "source": str(row["file"]),
                    "output": str(destination),
                    "explained_class": explained_class,
                    "regions": [
                        {
                            "x": item.x,
                            "y": item.y,
                            "width": item.width,
                            "height": item.height,
                            "strength": item.strength,
                        }
                        for item in regions
                    ],
                }
            )
        summary["classes"][class_name] = entries

    destination = reports_dir / "class_details.json"
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nCLASS DETAIL REPORT CREATED")
    print("=" * 60)
    for class_name, entries in summary["classes"].items():
        print(f"{class_name}: {len(entries)} analyzed TRAIN image(s)")
    print(f"Saved under: {reports_dir}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Show which special visual regions the CNN uses for each core type.")
    parser.add_argument("--artifact", default="artifacts/core_classifier_v2")
    parser.add_argument("--images-per-class", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=0.62)
    args = parser.parse_args()
    generate_class_detail_report(args.artifact, args.images_per_class, args.threshold)


if __name__ == "__main__":
    main()
