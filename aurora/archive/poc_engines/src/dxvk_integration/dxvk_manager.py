#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7c: DXVK Integration
==============================================

Manages the DXVK layer: extraction, DLL installation to the Wine prefix,
and configuration file generation. In production (Phase 8), this would:
- Extract the bundled DXVK .tzst archive
- Copy d3d9.dll, d3d10.dll, d3d11.dll, dxgi.dll to wineprefix/drive_c/windows/system32/
- Write dxvk.conf with per-game settings

For PoC, we simulate extraction + config generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# =============================================================================
# DXVK version registry (mirrors Winlator's installable_components/dxvk/)
# =============================================================================

@dataclass
class DXVKVersion:
    version: str         # e.g. "2.6.1"
    archive: str         # e.g. "dxvk-2.6.1.tzst"
    d3d9: bool = True    # Supports D3D9
    d3d10: bool = True   # Supports D3D10
    d3d11: bool = True   # Supports D3D11
    gpl_async: bool = True  # Has GPL async patch (stutter reduction)
    description: str = ""


DXVK_VERSIONS: list[DXVKVersion] = [
    DXVKVersion("1.7.2", "dxvk-1.7.2.tzst", True, True, True, False, "Older, for legacy games"),
    DXVKVersion("2.2", "dxvk-2.2.tzst", True, True, True, True, "Stable"),
    DXVKVersion("2.5.2", "dxvk-2.5.2.tzst", True, True, True, True, "Stable"),
    DXVKVersion("2.6.1", "dxvk-2.6.1.tzst", True, True, True, True, "Latest stable, recommended"),
]


# =============================================================================
# DXVK config (per-game dxvk.conf)
# =============================================================================

@dataclass
class DXVKConfig:
    """Per-game DXVK configuration. Written to dxvk.conf."""
    max_device_memory: int = 0          # 0 = auto-detect
    max_feature_level: str = "11_1"     # Max D3D feature level
    framerate: int = 0                  # 0 = uncapped
    async_pipeline: bool = True         # DXVK_GPLASYNCCACHE (stutter reduction)
    async_shader_compile: bool = True   # DXVK_ASYNC
    custom_device_id: str = ""          # Spoof GPU device ID (e.g. "0x1B06")
    custom_vendor_id: str = ""          # Spoof GPU vendor ID (e.g. "0x10de" = NVIDIA)
    custom_device_desc: str = ""        # Spoof GPU name
    constant_buffer_range_check: bool = False  # Stability workaround
    strict_shader_math: bool = True     # Stricter shader math (fixes some games)

    def to_config_string(self) -> str:
        """Generate the dxvk.conf content."""
        lines = ["# Aurora Emulator - DXVK configuration (per-game)", ""]

        if self.max_device_memory > 0:
            lines.append(f"dxgi.maxDeviceMemory = {self.max_device_memory}")
            lines.append(f"dxgi.maxSharedMemory = {self.max_device_memory * 2}")
        if self.max_feature_level:
            lines.append(f"d3d11.maxFeatureLevel = {self.max_feature_level}")
        if self.framerate > 0:
            lines.append(f"d3d11.maxFrameRate = {self.framerate}")
        if self.custom_device_id:
            lines.append(f"dxgi.customDeviceId = {self.custom_device_id}")
            lines.append(f"d3d9.customDeviceId = {self.custom_device_id}")
        if self.custom_vendor_id:
            lines.append(f"dxgi.customVendorId = {self.custom_vendor_id}")
            lines.append(f"d3d9.customVendorId = {self.custom_vendor_id}")
        if self.custom_device_desc:
            lines.append(f'dxgi.customDeviceDesc = "{self.custom_device_desc}"')
            lines.append(f'd3d9.customDeviceDesc = "{self.custom_device_desc}"')
        if self.constant_buffer_range_check:
            lines.append('d3d11.constantBufferRangeCheck = True')
        if self.strict_shader_math:
            lines.append('d3d11.relaxedBarriers = False')
            lines.append('d3d11.invariantPosition = True')

        return "\n".join(lines) + "\n"


# =============================================================================
# DXVK DLLs that get installed to system32
# =============================================================================

DXVK_DLLS: list[str] = [
    "d3d9.dll",
    "d3d10.dll",
    "d3d10_1.dll",
    "d3d10core.dll",
    "d3d11.dll",
    "dxgi.dll",
]


# =============================================================================
# DXVK manager
# =============================================================================

class DXVKManager:
    """Manages DXVK extraction + DLL installation + config."""

    def __init__(self, imagefs_root: Path, wineprefix: Path,
                 archive_dir: Optional[Path] = None):
        self.imagefs_root = Path(imagefs_root)
        self.wineprefix = Path(wineprefix)
        self.archive_dir = archive_dir or self.imagefs_root.parent / "installable_components" / "dxvk"
        self.system32 = self.wineprefix / "drive_c" / "windows" / "system32"
        self.config_path = self.imagefs_root / "home" / "xuser" / ".config" / "dxvk.conf"

    def get_available_versions(self) -> list[DXVKVersion]:
        return list(DXVK_VERSIONS)

    def extract(self, version: str) -> list[Path]:
        """Extract DXVK + install DLLs to system32.
        In production: tar --zstd -xf <archive>, then copy DLLs to system32."""
        if version not in [v.version for v in DXVK_VERSIONS]:
            raise ValueError(f"Unknown DXVK version: {version}")

        archive = self.archive_dir / f"dxvk-{version}.tzst"
        print(f"  [DXVKManager] Extracting {archive.name}")
        print(f"  [DXVKManager] (In production: tar --zstd -xf {archive.name} -C /tmp/dxvk-extract)")

        # PoC: create dummy DLL files in system32
        self.system32.mkdir(parents=True, exist_ok=True)
        installed_dlls: list[Path] = []
        for dll_name in DXVK_DLLS:
            dll_path = self.system32 / dll_name
            dll_path.write_bytes(b"PoC DXVK DLL")
            installed_dlls.append(dll_path)

        print(f"  [DXVKManager] Installed {len(installed_dlls)} DLLs to {self.system32}")
        return installed_dlls

    def write_config(self, config: DXVKConfig) -> Path:
        """Write the per-game dxvk.conf."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(config.to_config_string())
        print(f"  [DXVKManager] Wrote config: {self.config_path}")
        return self.config_path

    def is_installed(self) -> bool:
        """Check if DXVK DLLs are installed."""
        return (self.system32 / "d3d11.dll").exists()
