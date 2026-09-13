from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import os

import yaml
from pydantic import BaseModel, ConfigDict


def _load_local_env() -> None:
    """Load backend/.env without requiring pydantic-settings/python-dotenv.

    Environment variables already defined by the shell always win.  The parser is
    intentionally small because this project only needs simple KEY=VALUE entries.
    """
    env_path = Path.cwd() / '.env'
    if not env_path.exists():
        # Also works when imported from another working directory (Alembic/tests).
        env_path = Path(__file__).resolve().parents[2] / '.env'
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()


class Settings(BaseModel):
    """Runtime settings backed by environment variables.

    This deliberately uses pydantic itself rather than pydantic-settings so a
    partially-created demo virtualenv cannot fail on an optional settings helper.
    """

    model_config = ConfigDict(extra='ignore')

    app_name: str = 'Smart Core Warehouse'
    api_prefix: str = '/api/v1'
    database_url: str = 'sqlite:///./warehouse.db'
    config_dir: str = '../config'
    cv_base_url: str | None = None
    cv_min_confidence: float = 0.80
    scale_base_url: str | None = None
    embedded_mode: str = 'mock'
    log_level: str = 'INFO'
    auto_seed_demo: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv('APP_NAME', 'Smart Core Warehouse'),
        api_prefix=os.getenv('API_PREFIX', '/api/v1'),
        database_url=os.getenv('DATABASE_URL', 'sqlite:///./warehouse.db'),
        config_dir=os.getenv('CONFIG_DIR', '../config'),
        cv_base_url=os.getenv('CV_BASE_URL') or None,
        cv_min_confidence=float(os.getenv('CV_MIN_CONFIDENCE', '0.80')),
        scale_base_url=os.getenv('SCALE_BASE_URL') or None,
        embedded_mode=os.getenv('EMBEDDED_MODE', 'mock'),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
        auto_seed_demo=os.getenv('AUTO_SEED_DEMO', 'true').lower() in {'1', 'true', 'yes', 'on'},
    )


def load_yaml(name: str) -> dict[str, Any]:
    settings = get_settings()
    p = Path(settings.config_dir) / name
    if not p.exists():
        # Docker and local execution may start from different working dirs.
        root = Path(__file__).resolve().parents[3]
        p = root / 'config' / name
    with p.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}
