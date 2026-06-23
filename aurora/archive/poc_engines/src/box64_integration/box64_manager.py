#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7c: Box64 Integration
================================================

Manages the Box64 binary: extraction, version selection, RC file generation,
and launch command building. In production (Phase 8), this would:
- Extract the bundled Box64 .tzst archive to imagefs/usr/local/bin/box64
- Write config.box64rc with per-game settings
- Launch: box64 <game.exe> with the env var matrix

For PoC, we simulate extraction + build the launch command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# =============================================================================
# Box64 version registry (mirrors Winlator's installable_components/box64/)
# =============================================================================

@dataclass
class Box64Version:
    """A bundled Box64 version."""
    version: str           # e.g. "0.3.7"
    archive: str           # e.g. "box64-0.3.7.tzst"
    description: str = ""
    recommended: bool = False


# Known Box64 versions (mirrors Winlator's installable_components/box64/index.txt)
BOX64_VERSIONS: list[Box64Version] = [
    Box64Version("0.3.3", "box64-0.3.3.tzst", "Older, more compatible", recommended=False),
    Box64Version("0.3.5", "box64-0.3.5.tzst", "Stable", recommended=False),
    Box64Version("0.3.7", "box64-0.3.7.tzst", "Latest stable, recommended", recommended=True),
]


# =============================================================================
# Box64 presets (mirrors GameNative's Box86_64Preset)
# =============================================================================

@dataclass
class Box64Preset:
    """A Box64 performance preset (sets BOX64_* env vars)."""
    name: str
    description: str
    env_vars: dict[str, str]


BOX64_PRESETS: dict[str, Box64Preset] = {
    "compatibility": Box64Preset(
        name="compatibility",
        description="Max compatibility (slower but fewer crashes)",
        env_vars={
            "BOX64_DYNAREC": "1",
            "BOX64_DYNAREC_STRONGMEM": "1",  # Stronger memory consistency
            "BOX64_DYNAREC_SAFEFLAGS": "1",
        },
    ),
    "performance": Box64Preset(
        name="performance",
        description="Max performance (faster but may crash in some games)",
        env_vars={
            "BOX64_DYNAREC": "1",
            "BOX64_DYNAREC_STRONGMEM": "0",
            "BOX64_DYNAREC_SAFEFLAGS": "0",
            "BOX64_DYNAREC_BIGBLOCK": "1",
        },
    ),
    "stability": Box64Preset(
        name="stability",
        description="Max stability (for Unity engine games)",
        env_vars={
            "BOX64_DYNAREC": "1",
            "BOX64_DYNAREC_STRONGMEM": "2",
            "BOX64_DYNAREC_SAFEFLAGS": "2",
            "BOX64_DYNAREC_BIGBLOCK": "0",
        },
    ),
}


# =============================================================================
# Box64 manager
# =============================================================================

class Box64Manager:
    """Manages Box64 binary extraction + version selection."""

    def __init__(self, imagefs_root: Path, archive_dir: Optional[Path] = None):
        self.imagefs_root = Path(imagefs_root)
        self.archive_dir = archive_dir or self.imagefs_root.parent / "installable_components" / "box64"
        self.binary_path = self.imagefs_root / "usr" / "local" / "bin" / "box64"
        self.rcfile_path = self.imagefs_root / "etc" / "config.box64rc"

    def get_available_versions(self) -> list[Box64Version]:
        """Get all available Box64 versions."""
        return list(BOX64_VERSIONS)

    def get_recommended_version(self) -> Box64Version:
        """Get the recommended Box64 version."""
        for v in BOX64_VERSIONS:
            if v.recommended:
                return v
        return BOX64_VERSIONS[-1]  # fallback to latest

    def extract(self, version: str) -> Path:
        """Extract a Box64 version to imagefs.
        In production: tar --zstd -xf <archive> -C <imagefs>
        For PoC: just create a dummy file."""
        if version not in [v.version for v in BOX64_VERSIONS]:
            raise ValueError(f"Unknown Box64 version: {version}")

        archive = self.archive_dir / f"box64-{version}.tzst"
        print(f"  [Box64Manager] Extracting {archive.name} -> {self.binary_path}")
        print(f"  [Box64Manager] (In production: tar --zstd -xf {archive.name} -C {self.imagefs_root})")

        # PoC: create a dummy binary file
        self.binary_path.parent.mkdir(parents=True, exist_ok=True)
        self.binary_path.write_bytes(b"#!/bin/sh\n# PoC Box64 binary (version {version})\necho 'Box64 {version} (simulated)'\n")
        self.binary_path.chmod(0o755)

        print(f"  [Box64Manager] Extracted to {self.binary_path}")
        return self.binary_path

    def write_rcfile(self, preset: Box64Preset, game_exe: Optional[str] = None) -> Path:
        """Write config.box64rc with per-game settings.
        Format mirrors Box64's .box64rc (INI-style)."""
        self.rcfile_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Aurora Emulator - Box64 configuration",
            f"# Preset: {preset.name} ({preset.description})",
            "",
        ]

        # Global section
        lines.append("[box64]")
        for k, v in preset.env_vars.items():
            lines.append(f"{k}={v}")
        lines.append("")

        # Per-game section (if game exe provided)
        if game_exe:
            exe_name = Path(game_exe).name.lower()
            lines.append(f"[{exe_name}]")
            # Unity engine games need stability preset
            if "unity" in exe_name.lower():
                lines.append("BOX64_DYNAREC_BIGBLOCK=0")
                lines.append("BOX64_DYNAREC_STRONGMEM=2")
            # Skyrim needs MMAP32=0 on Mali (already in env vars, but reinforce)
            if "tesv" in exe_name or "skyrim" in exe_name:
                lines.append("BOX64_MMAP32=0")
            lines.append("")

        self.rcfile_path.write_text("\n".join(lines))
        print(f"  [Box64Manager] Wrote rcfile: {self.rcfile_path}")
        return self.rcfile_path

    def build_launch_command(
        self,
        game_exe: str,
        preset: Box64Preset,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        """Build the Box64 launch command.
        Returns a list suitable for subprocess.run()."""
        cmd = [
            str(self.binary_path),
            game_exe,
        ]
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    def is_extracted(self) -> bool:
        """Check if Box64 has been extracted."""
        return self.binary_path.exists() and self.binary_path.stat().st_size > 0
