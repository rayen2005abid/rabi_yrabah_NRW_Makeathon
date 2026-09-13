from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(payload: Any, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_image(path: str | Path) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Validate an image and return basic metadata without mutating it."""
    path = Path(path)
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            metadata = {
                "width": int(image.width),
                "height": int(image.height),
                "mode": str(image.mode),
                "format": str(image.format) if image.format else None,
            }
        return True, None, metadata
    except Exception as exc:  # Pillow raises several exception types for corrupt data.
        return False, f"{type(exc).__name__}: {exc}", None


def copy_preserving_name(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}_{sha256_file(source)[:8]}{source.suffix}"
    shutil.copy2(source, destination)
    return destination


def image_files(directory: Path, supported_extensions: Iterable[str]) -> list[Path]:
    extensions = {ext.lower() for ext in supported_extensions}
    return sorted(
        path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in extensions
    )
