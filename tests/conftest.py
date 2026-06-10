"""Pytest configuration: make the custom_components package importable."""

import sys
from pathlib import Path

# Repo root holds the implicit-namespace package `custom_components`.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
