"""Shared local assets for agent-driven video production, independent of any UI."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = Path(os.environ.get("A8_RESOURCES", ROOT / "cache" / "resources")).expanduser().resolve()
