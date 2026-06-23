#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Per-game Container config
=====================================================

Per-game configuration. Mirrors GameNative's Container.java pattern
(see docs/REFERENCE_ARCHITECTURE.md §5).

Each game gets its own Container with:
- screenSize, envVars, graphicsDriver, dxwrapper, dxwrapperConfig
- Aurora additions: auroraTextureQuality, auroraMeshLODBias,
  auroraPrefetchEnabled, auroraShaderCloudSync, auroraMaliSanitizer
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


# =============================================================================
# Default values (from GameNative's Container.java)
# =============================================================================

DEFAULT_SCREEN_SIZE = "1280x720"
DEFAULT_GRAPHICS_DRIVER = "turnip"  # Adreno; would be "panvk" for Mali, "virgl" fallback
DEFAULT_AUDIO_DRIVER = "pulseaudio"
DEFAULT_DXWRAPPER = "dxvk"
DEFAULT_BOX64_PRESET = "compatibility"

# GameNative's DEFAULT_ENV_VARS - tuned by thousands of users
DEFAULT_ENV_VARS_STR = (
    "WRAPPER_MAX_IMAGE_COUNT=0 "
    "ZINK_DESCRIPTORS=lazy "
    "ZINK_DEBUG=compact,deck_emu "
    "MESA_SHADER_CACHE_DISABLE=false "
    "MESA_SHADER_CACHE_MAX_SIZE=512MB "
    "mesa_glthread=true "
    "WINEESYNC=1 "
    "MESA_VK_WSI_PRESENT_MODE=mailbox "
    "TU_DEBUG=noconform "
    "VKD3D_SHADER_MODEL=6_0 "
    "PULSE_LATENCY_MSEC=144"
)

# Default DXVK config (GameNative's DEFAULT_DXWRAPPERCONFIG)
DEFAULT_DXVK_CONFIG = (
    "version=2.6.1,"
    "framerate=0,"
    "maxDeviceMemory=0,"
    "async=1,"
    "asyncCache=1,"
    "vkd3dVersion=3.0b,"
    "vkd3dLevel=12_1,"
    "csmt=3,"
    "gpuName=NVIDIA GeForce GTX 480,"
    "videoMemorySize=2048,"
    "strict_shader_math=1,"
    "OffscreenRenderingMode=fbo,"
    "renderer=gl"
)


# =============================================================================
# Container
# =============================================================================

@dataclass
class Container:
    """
    Per-game configuration. One Container per game.

    In production (Phase 8), this would be persisted as JSON in the app's
    private storage. For PoC, we just use the dataclass.
    """
    id: str                                    # unique container ID (e.g. "witcher3_1.32")
    name: str = ""                             # human-readable name
    screenSize: str = DEFAULT_SCREEN_SIZE      # e.g. "1280x720"
    envVars: str = DEFAULT_ENV_VARS_STR        # space-separated KEY=VAL pairs
    graphicsDriver: str = DEFAULT_GRAPHICS_DRIVER
    audioDriver: str = DEFAULT_AUDIO_DRIVER
    dxwrapper: str = DEFAULT_DXWRAPPER
    dxwrapperConfig: str = DEFAULT_DXVK_CONFIG
    box64Preset: str = DEFAULT_BOX64_PRESET    # compatibility / performance / stability
    box64Version: str = "0.3.7"
    wineVersion: str = "9.0"
    startupSelection: str = "normal"           # normal / essential / aggressive
    suspendPolicy: str = "auto"                # auto / never / manual

    # Parsed DXVK config fields (derived from dxwrapperConfig string)
    framerate: int = 0
    max_device_memory: int = 0
    max_feature_level: str = "11_1"
    dxvk_async: bool = True
    dxvk_async_cache: bool = True

    # Aurora-specific fields (NEW - Phases 1-4, 6)
    aurora_texture_quality: str = "default"     # fast / default / max (Phase 1)
    aurora_mesh_lod_bias: int = 0               # -2 to +2 (Phase 2)
    aurora_prefetch_enabled: bool = True        # Phase 3
    aurora_prefetch_threshold: float = 0.30     # Phase 3
    aurora_shader_cloud_sync: bool = True       # Phase 4
    aurora_mali_sanitizer: str = "auto"         # auto / on / off (Phase 6)

    @classmethod
    def create(cls, container_id: str, name: str = "") -> "Container":
        """Create a new Container with default settings."""
        if not container_id:
            raise ValueError("container_id cannot be empty")
        c = cls(id=container_id, name=name or container_id)
        c._parse_dxvk_config()
        return c

    def _parse_dxvk_config(self) -> None:
        """Parse the dxwrapperConfig string into individual fields."""
        # Format: "version=2.6.1,framerate=0,maxDeviceMemory=0,async=1,asyncCache=1,..."
        if not self.dxwrapperConfig:
            return
        for pair in self.dxwrapperConfig.split(","):
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "framerate":
                try:
                    self.framerate = int(v)
                except ValueError:
                    pass
            elif k == "maxDeviceMemory":
                try:
                    self.max_device_memory = int(v)
                except ValueError:
                    pass
            elif k == "async":
                self.dxvk_async = v != "0"
            elif k == "asyncCache":
                self.dxvk_async_cache = v != "0"

    def to_json(self) -> str:
        """Serialize to JSON for persistence."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "Container":
        """Deserialize from JSON."""
        data = json.loads(json_str)
        c = cls(**data)
        c._parse_dxvk_config()
        return c

    def save(self, path: Path) -> None:
        """Save container config to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())

    @classmethod
    def load(cls, path: Path) -> "Container":
        """Load container config from a JSON file."""
        return cls.from_json(path.read_text())

    def summary(self) -> dict:
        """Return a summary for logging."""
        return {
            "id": self.id,
            "name": self.name,
            "screenSize": self.screenSize,
            "graphicsDriver": self.graphicsDriver,
            "dxwrapper": self.dxwrapper,
            "box64Version": self.box64Version,
            "wineVersion": self.wineVersion,
            "aurora": {
                "textureQuality": self.aurora_texture_quality,
                "meshLODBias": self.aurora_mesh_lod_bias,
                "prefetchEnabled": self.aurora_prefetch_enabled,
                "shaderCloudSync": self.aurora_shader_cloud_sync,
                "maliSanitizer": self.aurora_mali_sanitizer,
            },
        }
