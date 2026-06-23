#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Environment Variable Matrix
========================================================

Builds the env var matrix for launching a game. Defaults are extracted from
GameNative's GlibcProgramLauncherComponent.execGuestProgram() and Container.java
(see docs/ENV_VAR_MATRIX.md for the full reference).

Aurora-specific env vars (Phases 1-4, 6) are added on top.

Usage:
    env_vars = EnvVars.from_defaults(image_fs, container, gpu_info)
    env_vars.put("EXTRA_VAR", "value")
    cmd = ["/usr/local/bin/box64", "/path/to/game.exe"]
    subprocess.run(cmd, env=env_vars.to_dict(), ...)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .aurora_imagefs import ImageFs
from .aurora_container import Container
from .aurora_gpu import GPUInfo


# =============================================================================
# EnvVars - ordered dict of environment variables
# =============================================================================

@dataclass
class EnvVars:
    """
    Ordered dict of environment variables. Order matters because later puts
    override earlier ones (matching GameNative's EnvVars.java behavior).
    """
    _vars: dict[str, str] = field(default_factory=dict)

    def put(self, key: str, value: str) -> "EnvVars":
        """Set an env var. Returns self for chaining."""
        if not key:
            raise ValueError("env var key cannot be empty")
        self._vars[key] = value
        return self

    def put_all(self, other: dict[str, str] | "EnvVars") -> "EnvVars":
        """Bulk-set env vars from a dict or another EnvVars."""
        if isinstance(other, EnvVars):
            other = other._vars
        for k, v in other.items():
            self.put(k, v)
        return self

    def get(self, key: str, default: str = "") -> str:
        return self._vars.get(key, default)

    def remove(self, key: str) -> "EnvVars":
        self._vars.pop(key, None)
        return self

    def to_dict(self) -> dict[str, str]:
        """Convert to a plain dict (for subprocess.run(env=...))."""
        return dict(self._vars)

    def to_array(self) -> list[str]:
        """Convert to a list of 'KEY=VALUE' strings (for execve)."""
        return [f"{k}={v}" for k, v in self._vars.items()]

    def items(self):
        return self._vars.items()

    def __contains__(self, key: str) -> bool:
        return key in self._vars

    def __len__(self) -> int:
        return len(self._vars)

    def __iter__(self):
        return iter(self._vars)

    @classmethod
    def from_defaults(
        cls,
        image_fs: ImageFs,
        container: Container,
        gpu_info: GPUInfo,
    ) -> "EnvVars":
        """
        Build the default env var matrix for launching a game.

        Args:
            image_fs: The ImageFs instance (filesystem layout)
            container: Per-game Container config (env var overrides, settings)
            gpu_info: GPU info (vendor, renderer, driver) - affects Box64/Mesa vars

        Returns:
            EnvVars instance with all defaults set. Caller can add more vars
            or override existing ones before launching.
        """
        ev = cls()

        # ----- Filesystem / runtime env (from GameNative) -----
        ev.put("HOME", image_fs.home_path)
        ev.put("USER", "xuser")
        ev.put("TMPDIR", str(image_fs.tmp_dir()))
        ev.put("DISPLAY", ":0")

        wine_bin = str(Path(image_fs.wine_path) / "bin")
        ev.put("PATH", f"{wine_bin}:{image_fs.root_dir}/usr/bin:{image_fs.root_dir}/usr/local/bin")
        ev.put("LD_LIBRARY_PATH", f"{image_fs.root_dir}/usr/lib")
        ev.put("BOX64_LD_LIBRARY_PATH", f"{image_fs.root_dir}/usr/lib/x86_64-linux-gnu")
        ev.put("FONTCONFIG_PATH", str(image_fs.root_dir / "etc" / "fonts"))
        ev.put("WINEESYNC_WINLATOR", "1")
        ev.put("WINEPREFIX", image_fs.wineprefix)

        # ----- Box64 tuning (from GameNative addBox64EnvVars) -----
        ev.put("BOX64_NOBANNER", "1")
        ev.put("BOX64_DYNAREC", "1")  # JIT compilation ON
        ev.put("BOX64_X11GLX", "1")
        ev.put("BOX64_RCFILE", str(image_fs.box64rc_file()))

        # CRITICAL: Mali-only workaround. Mali driver has a bug with 32-bit
        # memory mappings; BOX64_MMAP32=0 disables Box64's 32-bit mmap path.
        # GameNative auto-detects Mali via GPUInformation.getRenderer().
        if gpu_info.is_mali:
            ev.put("BOX64_MMAP32", "0")

        # ----- DXVK / graphics (from GameNative DXVKHelper + Container defaults) -----
        ev.put("DXVK_STATE_CACHE_PATH", str(image_fs.dxvk_state_cache_path()))
        ev.put("DXVK_LOG_LEVEL", "none")
        ev.put("DXVK_CONFIG_FILE", str(image_fs.dxvk_config_file()))

        # Magic stutter reduction flags
        if container.dxvk_async_cache:
            ev.put("DXVK_GPLASYNCCACHE", "1")  # async pipeline library cache
        if container.dxvk_async:
            ev.put("DXVK_ASYNC", "1")  # async shader compilation

        if container.max_device_memory > 0:
            ev.put("DXVK_FEATURE_LEVEL", container.max_feature_level)
        if container.framerate > 0:
            ev.put("DXVK_FRAME_RATE", str(container.framerate))

        # ----- Mesa (from Container.DEFAULT_ENV_VARS) -----
        ev.put("MESA_SHADER_CACHE_DISABLE", "false")
        ev.put("MESA_SHADER_CACHE_MAX_SIZE", "512MB")
        ev.put("MESA_VK_WSI_PRESENT_MODE", "mailbox")
        ev.put("mesa_glthread", "true")
        ev.put("ZINK_DESCRIPTORS", "lazy")
        ev.put("ZINK_DEBUG", "compact,deck_emu")

        # Turnip-specific speed hack (skip Vulkan conformance checks)
        # Only set for Adreno/Turnip, NOT Mali (Mali driver is already non-conformant)
        if gpu_info.is_adreno:
            ev.put("TU_DEBUG", "noconform")

        ev.put("VKD3D_SHADER_MODEL", "6_0")
        ev.put("WINEESYNC", "1")

        # ----- Audio (from Container.DEFAULT_ENV_VARS) -----
        ev.put("PULSE_LATENCY_MSEC", "144")

        # ----- Aurora-specific env vars (NEW - Phases 1-4 + 6) -----
        # Phase 1: Texture Engine
        ev.put("AURORA_AOT_TEXTURES_PATH", str(image_fs.aurora_textures_path()))
        ev.put("AURORA_TEXTURE_QUALITY", container.aurora_texture_quality)

        # Phase 2: Mesh Engine
        ev.put("AURORA_AOT_MESHES_PATH", str(image_fs.aurora_meshes_path()))
        ev.put("AURORA_MESH_LOD_BIAS", str(container.aurora_mesh_lod_bias))

        # Phase 3: Loader Engine
        if container.aurora_prefetch_enabled:
            ev.put("AURORA_PREFETCH_ENABLED", "1")
            ev.put("AURORA_PREFETCH_MODEL",
                   str(image_fs.aurora_prefetch_path() / "model.json"))
            ev.put("AURORA_PREFETCH_THRESHOLD",
                   str(container.aurora_prefetch_threshold))

        # Phase 4: Shader Engine
        if container.aurora_shader_cloud_sync:
            ev.put("AURORA_SHADER_CACHE_SYNC", "1")
            ev.put("AURORA_SHADER_CACHE_CLOUD", "https://cloud.aurora-emulator.org")

        # Phase 6: Mali sanitizer (only relevant for Mali GPUs)
        if gpu_info.is_mali and container.aurora_mali_sanitizer != "off":
            ev.put("AURORA_MALI_SANITIZER", container.aurora_mali_sanitizer)

        # ----- Per-game env var overrides (highest priority) -----
        # Container.envVars is a string like "KEY=VAL KEY2=VAL2" (GameNative format)
        if container.envVars:
            for pair in container.envVars.split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    ev.put(k, v)

        # ----- GPU-specific filtering (override the container defaults) -----
        # GameNative's DEFAULT_ENV_VARS includes "TU_DEBUG=noconform" but this is
        # a Turnip-only speed hack. On Mali it can cause crashes (Mali driver is
        # already non-conformant in places; this flag pushes it over the edge).
        # Remove it for non-Adreno GPUs.
        if not gpu_info.is_adreno and "TU_DEBUG" in ev:
            ev.remove("TU_DEBUG")

        return ev

    def __repr__(self) -> str:
        return f"EnvVars({len(self._vars)} vars)"
