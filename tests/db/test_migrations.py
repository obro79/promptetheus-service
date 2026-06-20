"""Migration structure checks for P2."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_verify_migrations_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_migrations.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
