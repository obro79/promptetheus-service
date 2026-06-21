"""Pytest bootstrap: make the ``promptetheus`` package importable.

The package lives under ``packages/promptetheus/`` and is intended to be used via
an editable install. In environments where the editable ``.pth`` is not applied
(some uv-managed venvs do not process bare-path ``.pth`` files at interpreter
startup), tests would fail to import ``promptetheus``. Prepending the package
root here makes the whole suite resolve regardless of install state. It is a
no-op when the package is already importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent / "packages" / "promptetheus"

if _PACKAGE_ROOT.is_dir():
    path_str = str(_PACKAGE_ROOT)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
