#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7c: Wine Integration
==============================================

Manages the Wine prefix: creation, DLL overrides, Win components configuration.
In production (Phase 8), this would:
- Extract the bundled Wine .tzst archive to imagefs/opt/wine/
- Initialize the Wine prefix (wineboot -i)
- Set DLL overrides (native,builtin for DXVK d3d9/d3d10/d3d11/d3d12)
- Configure Win components (direct3d, directsound, vcrun2010, etc.)

For PoC, we simulate prefix setup + build the DLL override config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# =============================================================================
# Wine version registry (mirrors Winlator/GameNative's bundled Wine versions)
# =============================================================================

@dataclass
class WineVersion:
    version: str          # e.g. "9.0"
    archive: str          # e.g. "wine-9.0.tzst"
    variant: str = "glibc"  # "glibc" or "bionic"
    wow64: bool = True      # WoW64 mode (32-bit x86 on 64-bit ARM)
    description: str = ""


WINE_VERSIONS: list[WineVersion] = [
    WineVersion("7.8", "wine-7.8.tzst", "glibc", True, "Older, for legacy games"),
    WineVersion("8.0", "wine-8.0.tzst", "glibc", True, "Stable"),
    WineVersion("9.0", "wine-9.0.tzst", "glibc", True, "Latest stable, recommended"),
]


# =============================================================================
# DLL overrides (mirrors GameNative's DEFAULT_WINCOMPONENTS)
# =============================================================================

# DXVK replaces these Windows DLLs with Vulkan-based implementations
DXVK_DLL_OVERRIDES: dict[str, str] = {
    "d3d9":   "native,builtin",   # DirectX 9
    "d3d10":  "native,builtin",   # DirectX 10
    "d3d10_1": "native,builtin",
    "d3d10core": "native,builtin",
    "d3d11":  "native,builtin",   # DirectX 11
    "d3d12":  "native,builtin",   # DirectX 12 (via VKD3D)
    "dxgi":   "native,builtin",   # DXGI (swap chain)
}

# VKD3D handles D3D12 (separate from DXVK)
VKD3D_DLL_OVERRIDES: dict[str, str] = {
    "d3d12": "native,builtin",
    "d3d12core": "native,builtin",
}

# WineD3D fallback (OpenGL-based, used when DXVK isn't installed)
WINED3D_DLL_OVERRIDES: dict[str, str] = {
    "wined3d": "builtin",
    "d3d9": "builtin",
    "d3d10": "builtin",
    "d3d11": "builtin",
}

# Default Win components (from GameNative's DEFAULT_WINCOMPONENTS)
# Format: component_name -> enabled (1=enable override, 0=disable)
DEFAULT_WINCOMPONENTS: dict[str, bool] = {
    "direct3d": True,       # DXVK replaces this
    "directsound": True,    # Wine's built-in DirectSound
    "directinput8": False,  # Disable (some games crash with it)
    "directinput": False,
    "directmusic": False,
    "directshow": False,
    "directplay": False,
    "vcrun2010": True,      # VC++ 2010 runtime
    "wmdecoder": True,      # Windows Media decoder
    "opengl": False,        # Disable OpenGL (use DXVK instead)
}


# =============================================================================
# Wine manager
# =============================================================================

class WineManager:
    """Manages the Wine prefix + DLL overrides."""

    def __init__(self, imagefs_root: Path, archive_dir: Optional[Path] = None):
        self.imagefs_root = Path(imagefs_root)
        self.archive_dir = archive_dir or self.imagefs_root.parent / "installable_components" / "wine"
        self.wine_bin_path = self.imagefs_root / "opt" / "wine" / "bin" / "wine"
        self.wineprefix = self.imagefs_root / "home" / "xuser" / ".wine"

    def get_available_versions(self) -> list[WineVersion]:
        return list(WINE_VERSIONS)

    def extract(self, version: str) -> Path:
        """Extract a Wine version to imagefs/opt/wine/.
        In production: tar --zstd -xf <archive> -C <imagefs>"""
        if version not in [v.version for v in WINE_VERSIONS]:
            raise ValueError(f"Unknown Wine version: {version}")

        archive = self.archive_dir / f"wine-{version}.tzst"
        print(f"  [WineManager] Extracting {archive.name} -> {self.wine_bin_path.parent}")
        print(f"  [WineManager] (In production: tar --zstd -xf {archive.name} -C {self.imagefs_root})")

        # PoC: create dummy wine binary
        self.wine_bin_path.parent.mkdir(parents=True, exist_ok=True)
        self.wine_bin_path.write_bytes(
            f"#!/bin/sh\n# PoC Wine binary (version {version})\necho 'Wine {version} (simulated)'\n".encode()
        )
        self.wine_bin_path.chmod(0o755)

        print(f"  [WineManager] Extracted to {self.wine_bin_path}")
        return self.wine_bin_path

    def init_prefix(self) -> Path:
        """Initialize the Wine prefix (wineboot -i).
        In production: WINEPREFIX=<prefix> wineboot -i"""
        self.wineprefix.mkdir(parents=True, exist_ok=True)
        # Create the drive_c structure
        (self.wineprefix / "drive_c").mkdir(exist_ok=True)
        (self.wineprefix / "drive_c" / "windows").mkdir(exist_ok=True)
        (self.wineprefix / "drive_c" / "windows" / "system32").mkdir(exist_ok=True)
        (self.wineprefix / "drive_c" / "Program Files").mkdir(exist_ok=True)

        print(f"  [WineManager] Initialized Wine prefix: {self.wineprefix}")
        print(f"  [WineManager] (In production: WINEPREFIX={self.wineprefix} wineboot -i)")
        return self.wineprefix

    def get_dll_overrides(self, dxwrapper: str = "dxvk") -> dict[str, str]:
        """Get DLL overrides for the specified DX wrapper.
        dxwrapper: "dxvk" (default), "vkd3d" (for D3D12), "wined3d" (OpenGL fallback), "none"
        """
        if dxwrapper == "dxvk":
            return dict(DXVK_DLL_OVERRIDES)
        elif dxwrapper == "vkd3d":
            return dict(VKD3D_DLL_OVERRIDES)
        elif dxwrapper == "wined3d":
            return dict(WINED3D_DLL_OVERRIDES)
        elif dxwrapper == "none":
            return {}
        else:
            raise ValueError(f"Unknown dxwrapper: {dxwrapper}")

    def build_dll_overrides_string(self, dxwrapper: str = "dxvk") -> str:
        """Build the WINEDLLOVERRIDES env var string.
        Format: d3d9=native,builtin;d3d11=native,builtin;..."""
        overrides = self.get_dll_overrides(dxwrapper)
        return ";".join(f"{k}={v}" for k, v in overrides.items())

    def is_extracted(self) -> bool:
        return self.wine_bin_path.exists() and self.wine_bin_path.stat().st_size > 0

    def is_prefix_initialized(self) -> bool:
        return (self.wineprefix / "drive_c" / "windows").is_dir()
