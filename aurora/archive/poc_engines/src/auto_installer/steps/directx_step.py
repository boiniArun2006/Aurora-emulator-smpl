#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: DirectX Step
=========================================

Auto-detects and installs DirectX runtime (DirectX 9.0c June 2010 redist).
Aurora-specific addition (not in GameNative).

Most pre-2015 Windows games require DirectX 9.0c runtime files
(d3dx9_*.dll, d3dcompiler_*.dll). The DirectX redist installer extracts
these to C:\\Windows\\System32 inside the Wine prefix.
"""

from __future__ import annotations

from pathlib import Path

from ..marker_utils import Marker, has_marker
from ..pre_install_step import PreInstallStep, InstallCommand


# Known DirectX installer paths (Windows paths, A:\ = game root)
DIRECTX_PATHS: list[tuple[str, str]] = [
    # Standard Steam/GOG layout
    ("A:\\_CommonRedist\\DirectX\\Jun2010\\DXSETUP.exe", "/silent"),
    ("A:\\_CommonRedist\\DirectX\\Jun2010_redist\\DXSETUP.exe", "/silent"),
    ("A:\\_CommonRedist\\DirectX\\Jun2010\\dxsetup.exe", "/silent"),
    # Older DirectX redist versions
    ("A:\\_CommonRedist\\DirectX\\Mar2009\\DXSETUP.exe", "/silent"),
    ("A:\\_CommonRedist\\DirectX\\Aug2008\\DXSETUP.exe", "/silent"),
    # Root-level DXSETUP
    ("A:\\DirectX\\DXSETUP.exe", "/silent"),
    ("A:\\redist\\DXSETUP.exe", "/silent"),
    # Some games put it in a Redist subdir
    ("A:\\Redist\\DirectX\\DXSETUP.exe", "/silent"),
    # GOG installers
    ("A:\\__Installer\\directx\\DXSETUP.exe", "/silent"),
    # EA/Origin games
    ("A:\\__Installer\\directx\\redist\\DXSETUP.exe", "/silent"),
]


class DirectXStep(PreInstallStep):
    """Auto-install DirectX 9.0c runtime."""

    @property
    def marker(self) -> Marker:
        return Marker.DIRECTX_INSTALLED

    @property
    def name(self) -> str:
        return "DirectX Runtime"

    def applies_to(self, game_dir: Path) -> bool:
        return not has_marker(game_dir, self.marker)

    def detect(self, game_dir: Path) -> list[InstallCommand]:
        commands: list[InstallCommand] = []
        for win_path, args in DIRECTX_PATHS:
            if not win_path.startswith("A:\\"):
                continue
            rest = win_path[3:]
            host_path = game_dir / rest.replace("\\", "/")
            if host_path.is_file():
                commands.append(InstallCommand(
                    executable=win_path,
                    args=args,
                    description="DirectX 9.0c Runtime",
                ))
                break  # Only need one DirectX install
        return commands
