#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: ImageFs
====================================

Sets up the fixed Linux-like filesystem layout inside the app's private storage.
Mirrors the pattern used by Winlator and GameNative (see docs/REFERENCE_ARCHITECTURE.md).

Layout:
    imagefs/                          # context.getFilesDir()/imagefs (PoC: a temp dir)
    ├── .img_version                  # version tag for migration
    ├── .variant                      # "glibc" or "bionic"
    ├── opt/
    │   └── wine/                     # Wine binaries
    │       └── bin/wine
    ├── home/xuser/                   # $HOME for Wine
    │   ├── .wine/                    # WINEPREFIX (registry, dosdevices, etc.)
    │   ├── .cache/                   # DXVK state cache, Mesa shader cache
    │   │   ├── dxvk_state/           # DXVK_STATE_CACHE_PATH (Phase 4)
    │   │   ├── mesa_shader_cache/    # MESA_SHADER_CACHE_DIR
    │   │   ├── aurora_textures/      # KTX2/UASTC files (Phase 1)
    │   │   ├── aurora_meshes/        # LOD .obj sets (Phase 2)
    │   │   └── aurora_prefetch/      # Markov model + play traces (Phase 3)
    │   └── .config/
    │       ├── dxvk.conf             # Per-game DXVK config
    │       └── aurora/               # Aurora-specific config
    ├── usr/
    │   ├── lib/                      # ARM64 shared libs
    │   │   └── x86_64-linux-gnu/     # BOX64_LD_LIBRARY_PATH target
    │   ├── bin/
    │   └── local/bin/box64           # Box64 binary
    ├── etc/
    │   ├── config.box64rc            # Box64 per-game config overrides
    │   └── fonts/
    └── tmp/

This is a PoC - in production this would be real Android private storage.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# =============================================================================
# Constants (mirror ImageFs.java from GameNative)
# =============================================================================

USER = "xuser"
HOME_PATH = f"/home/{USER}"
CACHE_PATH = f"{HOME_PATH}/.cache"
CONFIG_PATH = f"{HOME_PATH}/.config"
WINEPREFIX = f"{HOME_PATH}/.wine"

# Current ImageFs version. Bump when the layout changes - triggers migration.
CURRENT_IMG_VERSION = 1
CURRENT_VARIANT = "glibc"  # we use the glibc variant (bundled glibc, like GameNative)


# =============================================================================
# ImageFs
# =============================================================================

@dataclass
class ImageFs:
    """
    Represents the ImageFs filesystem layout.

    In production (Phase 8), root_dir would be context.getFilesDir()/imagefs.
    For PoC, we use a temp directory.
    """
    root_dir: Path

    # Derived paths (computed once, cached)
    wine_path: str = ""
    home_path: str = ""
    cache_path: str = ""
    config_path: str = ""
    wineprefix: str = ""

    @classmethod
    def create(cls, root_dir: Path) -> "ImageFs":
        """Create a new ImageFs at the given root directory."""
        root_dir = Path(root_dir).resolve()
        if root_dir.exists():
            shutil.rmtree(root_dir)
        root_dir.mkdir(parents=True)

        fs = cls(root_dir=root_dir)
        fs.wine_path = str(root_dir / "opt" / "wine")
        fs.home_path = str(root_dir / "home" / USER)
        fs.cache_path = str(root_dir / "home" / USER / ".cache")
        fs.config_path = str(root_dir / "home" / USER / ".config")
        fs.wineprefix = str(root_dir / "home" / USER / ".wine")
        fs._create_layout()
        fs._write_version_files()
        return fs

    @classmethod
    def open(cls, root_dir: Path) -> "ImageFs":
        """Open an existing ImageFs (must already exist)."""
        root_dir = Path(root_dir).resolve()
        if not root_dir.is_dir():
            raise FileNotFoundError(f"ImageFs not found at {root_dir}")
        version_file = root_dir / ".img_version"
        if not version_file.exists():
            raise RuntimeError(f"Not a valid ImageFs: missing .img_version at {root_dir}")

        fs = cls(root_dir=root_dir)
        fs.wine_path = str(root_dir / "opt" / "wine")
        fs.home_path = str(root_dir / "home" / USER)
        fs.cache_path = str(root_dir / "home" / USER / ".cache")
        fs.config_path = str(root_dir / "home" / USER / ".config")
        fs.wineprefix = str(root_dir / "home" / USER / ".wine")
        return fs

    def _create_layout(self) -> None:
        """Create all required directories in the ImageFs."""
        dirs = [
            "opt/wine/bin",
            "home/xuser/.wine/drive_c",
            "home/xuser/.cache/dxvk_state",
            "home/xuser/.cache/mesa_shader_cache",
            "home/xuser/.cache/aurora_textures",
            "home/xuser/.cache/aurora_meshes",
            "home/xuser/.cache/aurora_prefetch",
            "home/xuser/.config/aurora",
            "usr/lib/x86_64-linux-gnu",
            "usr/bin",
            "usr/local/bin",
            "etc/fonts",
            "tmp",
        ]
        for d in dirs:
            (self.root_dir / d).mkdir(parents=True, exist_ok=True)

    def _write_version_files(self) -> None:
        """Write .img_version and .variant files."""
        (self.root_dir / ".img_version").write_text(str(CURRENT_IMG_VERSION))
        (self.root_dir / ".variant").write_text(CURRENT_VARIANT)

    def get_version(self) -> int:
        """Read the .img_version file."""
        v_file = self.root_dir / ".img_version"
        if not v_file.exists():
            return 0
        try:
            return int(v_file.read_text().strip())
        except ValueError:
            return 0

    def get_variant(self) -> str:
        """Read the .variant file."""
        v_file = self.root_dir / ".variant"
        if not v_file.exists():
            return ""
        return v_file.read_text().strip()

    def is_valid(self) -> bool:
        """Check if this is a valid ImageFs."""
        return self.root_dir.is_dir() and (self.root_dir / ".img_version").exists()

    # Cache paths (where Aurora engines write their outputs)
    def dxvk_state_cache_path(self) -> Path:
        """Where DXVK writes its state cache (DXVK_STATE_CACHE_PATH env var).
        Phase 4 populates this from cloud before game launch."""
        return Path(self.cache_path) / "dxvk_state"

    def mesa_shader_cache_path(self) -> Path:
        """Where Mesa stores its shader cache (MESA_SHADER_CACHE_DIR env var)."""
        return Path(self.cache_path) / "mesa_shader_cache"

    def aurora_textures_path(self) -> Path:
        """Where Phase 1 stores KTX2/UASTC textures (AURORA_AOT_TEXTURES_PATH)."""
        return Path(self.cache_path) / "aurora_textures"

    def aurora_meshes_path(self) -> Path:
        """Where Phase 2 stores LOD mesh sets (AURORA_AOT_MESHES_PATH)."""
        return Path(self.cache_path) / "aurora_meshes"

    def aurora_prefetch_path(self) -> Path:
        """Where Phase 3 stores the Markov model + play traces (AURORA_PREFETCH_MODEL)."""
        return Path(self.cache_path) / "aurora_prefetch"

    def aurora_config_path(self) -> Path:
        """Where Aurora stores its per-install config."""
        return Path(self.config_path) / "aurora"

    def dxvk_config_file(self) -> Path:
        """Path to dxvk.conf (DXVK_CONFIG_FILE env var)."""
        return Path(self.config_path) / "dxvk.conf"

    def box64rc_file(self) -> Path:
        """Path to config.box64rc (BOX64_RCFILE env var)."""
        return self.root_dir / "etc" / "config.box64rc"

    def box64_binary(self) -> Path:
        """Path to the Box64 binary."""
        return self.root_dir / "usr" / "local" / "bin" / "box64"

    def wine_binary(self) -> Path:
        """Path to the Wine binary."""
        return Path(self.wine_path) / "bin" / "wine"

    def tmp_dir(self) -> Path:
        """Path to the tmp directory."""
        return self.root_dir / "tmp"

    def summary(self) -> dict:
        """Return a summary of the ImageFs layout for logging."""
        return {
            "root_dir": str(self.root_dir),
            "version": self.get_version(),
            "variant": self.get_variant(),
            "wine_path": self.wine_path,
            "home_path": self.home_path,
            "cache_path": self.cache_path,
            "config_path": self.config_path,
            "wineprefix": self.wineprefix,
            "aurora_paths": {
                "textures": str(self.aurora_textures_path()),
                "meshes": str(self.aurora_meshes_path()),
                "prefetch": str(self.aurora_prefetch_path()),
                "dxvk_state": str(self.dxvk_state_cache_path()),
                "mesa_shader": str(self.mesa_shader_cache_path()),
            },
        }
