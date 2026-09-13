"""Smart Core Warehouse computer-vision package."""

from __future__ import annotations

import sys


if sys.platform == "win32" and sys.version_info >= (3, 14):
    raise RuntimeError(
        "Unsupported Windows runtime for this project: Python 3.14+. "
        "The current OpenCV/NumPy dependency combination can install an experimental "
        "NumPy build on Python 3.14 and crash during import. Install Python 3.12 "
        "(recommended) or Python 3.11/3.13, create a fresh virtual environment, "
        "and reinstall requirements. See setup_windows.ps1."
    )
