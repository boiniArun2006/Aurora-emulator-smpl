#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Texture Engine Component
====================================================

Wraps Phase 1's AOT Texture Transcoder. On install, preprocesses game textures
to KTX2/UASTC. At runtime, sets AURORA_AOT_TEXTURES_PATH so the (future) runtime
texture loader knows where to find them.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

# Add src/ to path so we can import the Phase 1 engine
import os
_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from texture_engine.aot_texture_transcoder import AOTTextureTranscoder
from .base import EnvironmentComponent


class TextureEngineComponent(EnvironmentComponent):
    """Phase 1 component: AOT texture transcoding (BCn -> KTX2/UASTC -> ASTC)."""

    def __init__(self, game_textures_dir: Optional[Path] = None,
                 quality: str = "default"):
        super().__init__(name="TextureEngine")
        self.game_textures_dir = game_textures_dir
        self.quality = quality
        self.transcoder: Optional[AOTTextureTranscoder] = None
        self.processed_count: int = 0
        self.process_time_ms: float = 0.0

    def preprocess_on_install(self) -> None:
        """Run AOT preprocessing on game install.
        This is the SLOW step (~3 sec per 1024x1024 texture) - only run once."""
        if not self.environment:
            raise RuntimeError("Component not attached to environment")
        if not self.game_textures_dir or not self.game_textures_dir.exists():
            print(f"  [TextureEngine] No textures to preprocess (dir={self.game_textures_dir})")
            return

        # Build transcoder with the container's quality setting
        self.transcoder = AOTTextureTranscoder(quality=self.quality)
        out_dir = self.environment.image_fs.aurora_textures_path()
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [TextureEngine] Preprocessing textures from {self.game_textures_dir}")
        print(f"  [TextureEngine] Quality: {self.quality}")
        print(f"  [TextureEngine] Output: {out_dir}")

        t0 = time.perf_counter()
        results = self.transcoder.process_directory(self.game_textures_dir, out_dir)
        self.process_time_ms = (time.perf_counter() - t0) * 1000.0
        self.processed_count = len(results)

        if results:
            total_ktx2 = sum(r.ktx2_size_bytes for r in results)
            total_raw = sum(r.raw_rgba_bytes for r in results)
            print(f"  [TextureEngine] Processed {self.processed_count} textures in {self.process_time_ms / 1000:.1f}s")
            print(f"  [TextureEngine] Compression: {total_raw / max(total_ktx2, 1):.2f}x vs raw RGBA")
        else:
            print(f"  [TextureEngine] No textures processed")

    def start(self) -> None:
        """At runtime, just verify the cache exists. The actual transcoding
        happens on install (preprocess_on_install)."""
        super().start()
        cache = self.environment.image_fs.aurora_textures_path()
        if cache.exists():
            ktx2_count = len(list(cache.glob("*.ktx2")))
            print(f"  [TextureEngine] Started. Cache: {ktx2_count} KTX2 files at {cache}")
        else:
            print(f"  [TextureEngine] Started. Cache empty (run preprocess_on_install first)")
