#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: Marker Utils
=========================================

Idempotency markers for the auto-installer. Each PreInstallStep writes a
marker file after successful installation so it doesn't run again.

Ported from GameNative's MarkerUtils.kt (MIT licensed).

Marker files are stored in <game_dir>/.aurora_markers/<MARKER_NAME>
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class Marker(Enum):
    """Markers for each pre-install step. Add new ones as steps are added."""
    VCREDIST_INSTALLED = "VCREDIST_INSTALLED"
    DIRECTX_INSTALLED = "DIRECTX_INSTALLED"
    PHYSX_INSTALLED = "PHYSX_INSTALLED"
    DOTNET_INSTALLED = "DOTNET_INSTALLED"
    OPENAL_INSTALLED = "OPENAL_INSTALLED"
    XNA_INSTALLED = "XNA_INSTALLED"
    UBISOFT_CONNECT_INSTALLED = "UBISOFT_CONNECT_INSTALLED"
    GOG_SCRIPT_RUN = "GOG_SCRIPT_RUN"


def _markers_dir(game_dir_path: str | Path) -> Path:
    """Get the markers directory for a game, creating it if needed."""
    d = Path(game_dir_path) / ".aurora_markers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def has_marker(game_dir_path: str | Path, marker: Marker) -> bool:
    """Check if a marker file exists."""
    marker_file = _markers_dir(game_dir_path) / marker.value
    return marker_file.exists()


def add_marker(game_dir_path: str | Path, marker: Marker) -> None:
    """Write a marker file (idempotent — safe to call multiple times)."""
    marker_file = _markers_dir(game_dir_path) / marker.value
    marker_file.touch()


def remove_marker(game_dir_path: str | Path, marker: Marker) -> None:
    """Remove a marker file (useful for re-running a step)."""
    marker_file = _markers_dir(game_dir_path) / marker.value
    if marker_file.exists():
        marker_file.unlink()


def list_markers(game_dir_path: str | Path) -> list[str]:
    """List all markers present for a game."""
    d = Path(game_dir_path) / ".aurora_markers"
    if not d.exists():
        return []
    return sorted(f.name for f in d.iterdir() if f.is_file())
