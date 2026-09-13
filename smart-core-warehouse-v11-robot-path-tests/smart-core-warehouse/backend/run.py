"""One-command local backend launcher.

Usage from backend/:
    python run.py

The launcher defaults to SQLite, repairs/synchronizes missing runtime
requirements when necessary, applies Alembic migrations, then starts Uvicorn.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

# Safe local defaults. Explicit environment variables still win.
os.environ.setdefault('DATABASE_URL', 'sqlite:///./warehouse.db')
os.environ.setdefault('CONFIG_DIR', str(Path(__file__).resolve().parents[1] / 'config'))
os.environ.setdefault('EMBEDDED_MODE', 'mock')
os.environ.setdefault('AUTO_SEED_DEMO', 'true')

# Package name -> import name.  Local SQLite does not need psycopg at startup,
# but all packages used by the base app are checked here.
_REQUIRED_IMPORTS = {
    'fastapi': 'fastapi',
    'uvicorn': 'uvicorn',
    'SQLAlchemy': 'sqlalchemy',
    'alembic': 'alembic',
    'pydantic': 'pydantic',
    'PyYAML': 'yaml',
    'httpx': 'httpx',
}


def _missing_runtime_packages() -> list[str]:
    return [package for package, module in _REQUIRED_IMPORTS.items() if importlib.util.find_spec(module) is None]


def ensure_dependencies() -> None:
    """Repair a stale/partial virtualenv before importing the application.

    This specifically prevents the common demo failure where a .venv exists but
    was created from an older ZIP and therefore never received a newer package.
    """
    missing = _missing_runtime_packages()
    if not missing:
        return

    requirements = Path(__file__).resolve().parent / 'requirements.txt'
    print('Backend environment is missing: ' + ', '.join(missing))
    print('Synchronizing dependencies from requirements.txt ...')
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', str(requirements)])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            '\nAutomatic dependency installation failed. Run this command manually:\n'
            f'  "{sys.executable}" -m pip install -r "{requirements}"\n'
        ) from exc

    still_missing = _missing_runtime_packages()
    if still_missing:
        raise SystemExit(
            'Dependencies are still missing after installation: ' + ', '.join(still_missing)
        )


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    here = Path(__file__).resolve().parent
    cfg = Config(str(here / 'alembic.ini'))
    cfg.set_main_option('script_location', str(here / 'migrations'))
    command.upgrade(cfg, 'head')


def main() -> None:
    ensure_dependencies()

    # Import only after dependency preflight so failures are clear and repairable.
    import uvicorn

    migrate()
    print('Smart Core Warehouse backend')
    print('  Geometry: 4 racks x 8 columns x 8 levels = 256 storage slots')
    print('  Health : http://localhost:8000/health')
    print('  Swagger: http://localhost:8000/docs')
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=True)


if __name__ == '__main__':
    main()
