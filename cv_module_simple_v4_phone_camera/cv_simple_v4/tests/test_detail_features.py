from pathlib import Path

import numpy as np
import torch
from PIL import Image

from src.explainability import green_attention_overlay, salient_regions
from src.inference import CoreClassifier
from src.models import extract_feature_embedding


def test_gradcam_detail_map_and_green_overlay(dummy_artifact: Path) -> None:
    classifier = CoreClassifier(dummy_artifact, device="cpu")
    image = Image.new("RGB", (96, 72), color=(140, 110, 80))
    result = classifier.predict_pil(image, top_k=5)
    attention, class_name = classifier.explain_pil(image, class_name=result.core_type)
    assert class_name == result.core_type
    assert attention.ndim == 2
    assert float(attention.min()) >= 0.0
    assert float(attention.max()) <= 1.0 + 1e-6

    bgr = np.full((72, 96, 3), 100, dtype=np.uint8)
    overlay = green_attention_overlay(bgr, attention, threshold=0.4)
    assert overlay.shape == bgr.shape
    regions = salient_regions(attention, 96, 72, threshold=0.4, max_regions=3)
    assert len(regions) <= 3


def test_prototype_assist_loads_and_keeps_probability_distribution(dummy_artifact: Path) -> None:
    base = CoreClassifier(dummy_artifact, device="cpu")
    image = Image.new("RGB", (96, 72), color=(120, 100, 80))
    tensor = base._prepare_tensor(image)
    with torch.no_grad():
        embedding = extract_feature_embedding(base.model, base.architecture, tensor)[0].cpu()
    prototypes = torch.stack([embedding.roll(i) for i in range(len(base.class_names))], dim=0)
    torch.save(
        {
            "class_names": base.class_names,
            "prototypes": prototypes,
            "counts": {name: 2 for name in base.class_names},
            "source_split": "train",
        },
        dummy_artifact / "feature_prototypes.pt",
    )

    assisted = CoreClassifier(dummy_artifact, device="cpu")
    result, diagnostics = assisted.predict_with_diagnostics(image, top_k=5)
    probabilities = [result.confidence] + [item.confidence for item in result.alternatives]
    assert diagnostics.prototype_assist_used is True
    assert diagnostics.prototype_probabilities is not None
    assert abs(sum(probabilities) - 1.0) < 1e-5


def test_build_feature_prototypes_uses_train_originals_only(
    dummy_artifact: Path, base_config: dict
) -> None:
    import pandas as pd
    from src.feature_prototypes import build_feature_prototypes

    raw_dir = Path(base_config["dataset"]["raw_dir"])
    classes = [f"CORE_{letter}" for letter in "ABCDE"]
    rows = []
    for class_index, class_name in enumerate(classes):
        for image_index in range(2):
            relative = Path(class_name) / f"img_{image_index}.jpg"
            path = raw_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB",
                (96, 72),
                color=(50 + class_index * 30, 70 + image_index * 20, 100),
            ).save(path)
            rows.append(
                {
                    "file": str(relative).replace("\\", "/"),
                    "class": class_name,
                    "sha256": f"{class_name}_{image_index}",
                    "split": "train",
                }
            )
    manifest = dummy_artifact.parent.parent / "manifest.csv"
    pd.DataFrame(rows).to_csv(manifest, index=False)

    destination = build_feature_prototypes(
        dummy_artifact,
        config=base_config,
        manifest_path=manifest,
    )
    payload = torch.load(destination, map_location="cpu", weights_only=False)
    assert payload["class_names"] == classes
    assert payload["prototypes"].shape[0] == 5
    assert payload["counts"] == {name: 2 for name in classes}
    assert payload["source_split"] == "train"
