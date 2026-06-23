#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Shader Engine Component
====================================================

Wraps Phase 4's shader cache. On install, downloads the cloud shader cache
for this game + GPU + driver combo. At runtime, populates DXVK_STATE_CACHE_PATH
so DXVK reads the pre-compiled pipelines (zero stutter).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from shader_engine.shader_cache import (
    LocalShaderCache, CloudShaderCache, generate_synthetic_pso_set,
)
from .base import EnvironmentComponent


class ShaderEngineComponent(EnvironmentComponent):
    """Phase 4 component: community cloud shader cache."""

    def __init__(self, cloud_root: Optional[Path] = None):
        super().__init__(name="ShaderEngine")
        self.cloud_root = cloud_root  # PoC: local dir simulating cloud
        self.downloaded_count: int = 0
        self.download_time_ms: float = 0.0
        self.cache_size_bytes: int = 0

    def preprocess_on_install(self) -> None:
        """Download the cloud shader cache on install.
        In production, this would fetch from a real cloud service.
        For PoC, we simulate by generating PSOs locally."""
        if not self.environment:
            raise RuntimeError("Component not attached to environment")

        image_fs = self.environment.image_fs
        gpu_info = self.environment.gpu_info
        container = self.environment.container

        # Map Aurora GPU info to shader cache vendor name
        if gpu_info.is_adreno:
            vendor = "adreno"
        elif gpu_info.is_mali:
            vendor = gpu_info.vendor  # mali_valhall or mali_immortalis
        else:
            print(f"  [ShaderEngine] Unsupported GPU vendor: {gpu_info.vendor}, skipping")
            return

        # Use the cloud root if provided, else use a temp dir
        if self.cloud_root is None:
            self.cloud_root = image_fs.root_dir.parent / "aurora_cloud_sim"
        self.cloud_root.mkdir(parents=True, exist_ok=True)

        print(f"  [ShaderEngine] Downloading shader cache")
        print(f"  [ShaderEngine] Game: {container.id}")
        print(f"  [ShaderEngine] GPU: {vendor} / {gpu_info.driver_version}")

        local_cache = LocalShaderCache(image_fs.dxvk_state_cache_path())
        cloud = CloudShaderCache(self.cloud_root)

        # Check if cloud has a manifest for this game+GPU+driver
        manifest = cloud.download_manifest(container.id, vendor, gpu_info.driver_version)
        if manifest is None:
            # PoC: simulate first user (no cloud cache yet) - generate PSOs locally
            print(f"  [ShaderEngine] No cloud cache yet (simulating first user)")
            print(f"  [ShaderEngine] Generating synthetic PSOs locally for PoC...")
            pso_data = generate_synthetic_pso_set(container.id, seed=42)
            entries = [e for e, _ in pso_data]
            binaries = {e.pso_hash: b for e, b in pso_data}
            # Upload to cloud (simulated)
            cloud.upload(container.id, vendor, gpu_info.driver_version, entries, binaries)
            manifest = cloud.download_manifest(container.id, vendor, gpu_info.driver_version)
            if manifest is None:
                print(f"  [ShaderEngine] FAIL: could not populate cloud")
                return

        # Download all binaries to local cache
        t0 = time.perf_counter()
        from shader_engine.shader_cache import PSOEntry
        pso_hashes = manifest["pso_hashes"]
        downloaded_entries: list[PSOEntry] = []

        # Build entries lookup (in production, cloud would store entry data)
        entries_by_hash = {}
        # Re-generate to get entry data (PoC only; production would fetch from cloud)
        for e, _ in generate_synthetic_pso_set(container.id, seed=42):
            entries_by_hash[e.pso_hash] = e

        for pso_hash in pso_hashes:
            binary = cloud.download_binary(container.id, vendor, gpu_info.driver_version, pso_hash)
            if binary is None:
                continue
            local_cache.store_binary(container.id, vendor, gpu_info.driver_version, pso_hash, binary)
            self.cache_size_bytes += len(binary)
            if pso_hash in entries_by_hash:
                downloaded_entries.append(entries_by_hash[pso_hash])

        # Write the state cache file (this is what DXVK reads)
        local_cache.write_state_cache(container.id, vendor, gpu_info.driver_version, downloaded_entries)
        self.download_time_ms = (time.perf_counter() - t0) * 1000.0
        self.downloaded_count = len(pso_hashes)

        print(f"  [ShaderEngine] Downloaded {self.downloaded_count} PSOs ({self.cache_size_bytes / 1024 / 1024:.1f} MB)")
        print(f"  [ShaderEngine] Download time: {self.download_time_ms:.1f}ms")

    def start(self) -> None:
        super().start()
        cache = self.environment.image_fs.dxvk_state_cache_path()
        # Count cache files
        if cache.exists():
            # Look for the state_cache.bin file (per-(game, GPU, driver))
            state_files = list(cache.rglob("state_cache.bin"))
            total_binaries = sum(1 for _ in cache.rglob("*.bin") if _.name != "state_cache.bin")
            print(f"  [ShaderEngine] Started. Cache: {total_binaries} PSOs across {len(state_files)} state files")
        else:
            print(f"  [ShaderEngine] Started. Cache empty (run preprocess_on_install first)")
