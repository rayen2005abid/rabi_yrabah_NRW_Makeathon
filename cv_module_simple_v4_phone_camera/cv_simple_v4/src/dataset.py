from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd
import torch
from PIL import Image
from torch.utils.data import Dataset


class CoreImageDataset(Dataset):
    """Dataset backed by a leakage-safe split manifest of original images."""

    def __init__(
        self,
        raw_dir: str | Path,
        manifest: str | Path | pd.DataFrame,
        split: str,
        transform: Callable | None,
        class_to_idx: dict[str, int] | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        frame = manifest.copy() if isinstance(manifest, pd.DataFrame) else pd.read_csv(manifest)
        self.frame = frame[frame["split"] == split].reset_index(drop=True)
        self.transform = transform
        classes = sorted(frame["class"].unique().tolist())
        self.class_to_idx = class_to_idx or {name: index for index, name in enumerate(classes)}
        self.idx_to_class = {index: name for name, index in self.class_to_idx.items()}
        self.split = split

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int, str]:
        row = self.frame.iloc[index]
        path = self.raw_dir / row["file"]
        with Image.open(path) as image:
            image = image.convert("RGB")
            if self.transform:
                image = self.transform(image)
        return image, self.class_to_idx[row["class"]], str(row["file"])

    @property
    def class_counts(self) -> dict[str, int]:
        return self.frame["class"].value_counts().sort_index().to_dict()
