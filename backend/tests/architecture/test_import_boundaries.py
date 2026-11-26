"""Boundary gate: the import-linter contracts in .importlinter must hold."""
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SURFACES = sorted(
    ".".join(path.relative_to(ROOT).with_suffix("").parts)
    for path in (ROOT / "app" / "modules").glob("*/contracts.py")
)


def test_import_linter_contracts_are_kept():
    # Separate process: import-linter reconfigures logging, which would leak into other tests.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from importlinter.cli import lint_imports; "
         "sys.exit(lint_imports(config_filename='.importlinter', no_cache=True, no_logo=True))"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", PUBLIC_SURFACES)
def test_each_public_surface_imports_first_without_cycles(module):
    # A fresh interpreter importing this surface first catches order-dependent import cycles.
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
