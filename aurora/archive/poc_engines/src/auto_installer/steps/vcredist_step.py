#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: VC++ Redistributable Step
======================================================

Auto-detects and installs Visual C++ Redistributables (2005-2019, x86+x64).
Ported from GameNative's VcRedistStep.kt (MIT licensed).

GameNative's 38-entry map covers all common VC++ installer locations used by
Steam, GOG, and direct-download games. We port it verbatim.
"""

from __future__ import annotations

from pathlib import Path

from ..marker_utils import Marker, has_marker
from ..pre_install_step import PreInstallStep, InstallCommand


# =============================================================================
# The 38-entry VC++ installer map (ported from GameNative VcRedistStep.kt)
# Format: Windows path -> installer arguments
# A:\ maps to the game's root directory inside the Wine prefix
# =============================================================================
VCREDIST_MAP: dict[str, str] = {
    # vcredist/ subdirectory layout (most common)
    "A:\\_CommonRedist\\vcredist\\2005\\vcredist_x86.exe": "/Q",
    "A:\\_CommonRedist\\vcredist\\2005\\vcredist_x64.exe": "/Q",
    "A:\\_CommonRedist\\vcredist\\2008\\vcredist_x86.exe": "/qb!",
    "A:\\_CommonRedist\\vcredist\\2008\\vcredist_x64.exe": "/qb!",
    "A:\\_CommonRedist\\vcredist\\2010\\vcredist_x86.exe": "/passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2010\\vcredist_x64.exe": "/passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2012\\vcredist_x86.exe": "/passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2012\\vcredist_x64.exe": "/passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2013\\vcredist_x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2013\\vcredist_x64.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2015\\vc_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2015\\vc_redist.x64.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2017\\vc_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2017\\vc_redist.x64.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2019\\vc_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\vcredist\\2019\\vc_redist.x64.exe": "/install /passive /norestart",
    # MSVC*/ subdirectory layout (older convention)
    "A:\\_CommonRedist\\MSVC2005\\vcredist_x86.exe": "/Q",
    "A:\\_CommonRedist\\MSVC2005_x64\\vcredist_x64.exe": "/Q",
    "A:\\_CommonRedist\\MSVC2008\\vcredist_x86.exe": "/qb!",
    "A:\\_CommonRedist\\MSVC2008_x64\\vcredist_x64.exe": "/qb!",
    "A:\\_CommonRedist\\MSVC2010\\vcredist_x86.exe": "/passive /norestart",
    "A:\\_CommonRedist\\MSVC2010_x64\\vcredist_x64.exe": "/passive /norestart",
    "A:\\_CommonRedist\\MSVC2012\\vcredist_x86.exe": "/passive /norestart",
    "A:\\_CommonRedist\\MSVC2012_x64\\vcredist_x64.exe": "/passive /norestart",
    "A:\\_CommonRedist\\MSVC2013\\vcredist_x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2013_x64\\vcredist_x64.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2015\\VC_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2015_x64\\VC_redist.x64.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2017\\VC_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2017_x64\\VC_redist.x64.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2019\\VC_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\MSVC2019_x64\\VC_redist.x64.exe": "/install /passive /norestart",
    # Root-level redist/ directory
    "A:\\redist\\vcredist_x86.exe": "",
    "A:\\redist\\vcredist_x64.exe": "",
    # Top-level _CommonRedist (no version subdirectory)
    "A:\\_CommonRedist\\VC_redist.x86.exe": "/install /passive /norestart",
    "A:\\_CommonRedist\\VC_redist.x64.exe": "/install /passive /norestart",
}


class VcRedistStep(PreInstallStep):
    """Auto-install Visual C++ Redistributables."""

    @property
    def marker(self) -> Marker:
        return Marker.VCREDIST_INSTALLED

    @property
    def name(self) -> str:
        return "VC++ Redistributables"

    def applies_to(self, game_dir: Path) -> bool:
        """Run if marker not yet present."""
        return not has_marker(game_dir, self.marker)

    def detect(self, game_dir: Path) -> list[InstallCommand]:
        """Scan game_dir for VC++ installers. Returns list of commands."""
        commands: list[InstallCommand] = []

        for win_path, args in VCREDIST_MAP.items():
            # Translate A:\_CommonRedist\... -> game_dir/_CommonRedist/...
            # The A:\ prefix maps to the game's root directory
            if not win_path.startswith("A:\\"):
                continue
            rest = win_path[3:]  # strip "A:\"
            host_path = game_dir / rest.replace("\\", "/")
            if host_path.is_file():
                # Extract version from path for description
                version = _extract_version_from_path(win_path)
                arch = "x64" if "x64" in win_path.lower() else "x86"
                commands.append(InstallCommand(
                    executable=win_path,
                    args=args,
                    description=f"VC++ {version} ({arch})",
                ))

        return commands


def _extract_version_from_path(win_path: str) -> str:
    """Extract version string from a VC++ installer path."""
    path_lower = win_path.lower()
    for year in ["2005", "2008", "2010", "2012", "2013", "2015", "2017", "2019"]:
        if year in path_lower:
            return year
    # Check for MSVC naming
    for year in ["2005", "2008", "2010", "2012", "2013", "2015", "2017", "2019"]:
        if f"msvc{year}" in path_lower:
            return year
    return "unknown"
