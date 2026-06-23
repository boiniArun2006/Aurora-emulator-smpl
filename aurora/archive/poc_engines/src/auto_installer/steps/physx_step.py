#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: PhysX Step
=======================================

Auto-detects and installs NVIDIA PhysX.
Ported from GameNative's PhysXStep.kt (MIT licensed).

PhysX is required by many 2008-2015 games (Borderlands, Batman Arkham series,
Mafia II, etc.). It comes as either an .msi or .exe installer in
_CommonRedist/PhysX/.
"""

from __future__ import annotations

from pathlib import Path

from ..marker_utils import Marker, has_marker
from ..pre_install_step import PreInstallStep, InstallCommand


# Known PhysX installer paths (Windows paths, A:\ = game root)
PHYSX_PATHS: list[tuple[str, str]] = [
    # MSI installers (preferred - more reliable silent install)
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.16.0318_SystemSoftware.msi", "/quiet /norestart"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.14.0702_SystemSoftware.msi", "/quiet /norestart"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.13.1220_SystemSoftware.msi", "/quiet /norestart"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.12.0613_SystemSoftware.msi", "/quiet /norestart"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.11.1111_SystemSoftware.msi", "/quiet /norestart"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_SystemSoftware.msi", "/quiet /norestart"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_legacy.msi", "/quiet /norestart"),
    # EXE installers (fallback)
    ("A:\\_CommonRedist\\PhysX\\PhysX_setup.exe", "/quiet"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.16.0318_SystemSoftware.exe", "/quiet"),
    ("A:\\_CommonRedist\\PhysX\\PhysX_9.14.0702_SystemSoftware.exe", "/quiet"),
    # Root-level
    ("A:\\PhysX\\PhysX_setup.exe", "/quiet"),
    ("A:\\redist\\PhysX\\PhysX_setup.exe", "/quiet"),
]


class PhysXStep(PreInstallStep):
    """Auto-install NVIDIA PhysX."""

    @property
    def marker(self) -> Marker:
        return Marker.PHYSX_INSTALLED

    @property
    def name(self) -> str:
        return "NVIDIA PhysX"

    def applies_to(self, game_dir: Path) -> bool:
        return not has_marker(game_dir, self.marker)

    def detect(self, game_dir: Path) -> list[InstallCommand]:
        commands: list[InstallCommand] = []
        for win_path, args in PHYSX_PATHS:
            if not win_path.startswith("A:\\"):
                continue
            rest = win_path[3:]
            host_path = game_dir / rest.replace("\\", "/")
            if host_path.is_file():
                # Extract version from filename for description
                version = "unknown"
                lower = win_path.lower()
                for v in ["9.16", "9.14", "9.13", "9.12", "9.11", "legacy"]:
                    if v in lower:
                        version = v
                        break
                commands.append(InstallCommand(
                    executable=win_path,
                    args=args,
                    description=f"PhysX {version}",
                ))
                break  # Only need one PhysX install
        return commands
