#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Mesh Engine Component
=================================================

Wraps Phase 2's AOT Mesh Simplifier. On install, simplifies game meshes to
multiple LOD levels. At runtime, sets AURORA_AOT_MESHES_PATH.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from mesh_engine.aot_mesh_simplifier import (
    generate_uv_sphere, simplify_mesh, compact_and_optimize_vertex_fetch,
    write_obj, SIMPLIFY_LOCK_BORDER,
)
from .base import EnvironmentComponent


class MeshEngineComponent(EnvironmentComponent):
    """Phase 2 component: AOT mesh simplification (QEM via meshoptimizer)."""

    def __init__(self, game_meshes_dir: Optional[Path] = None,
                 lod_bias: int = 0):
        super().__init__(name="MeshEngine")
        self.game_meshes_dir = game_meshes_dir
        self.lod_bias = lod_bias  # -2 = more aggressive, +2 = less
        self.processed_count: int = 0
        self.process_time_ms: float = 0.0

    def preprocess_on_install(self) -> None:
        """Run AOT mesh simplification on game install."""
        if not self.environment:
            raise RuntimeError("Component not attached to environment")
        out_dir = self.environment.image_fs.aurora_meshes_path()
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [MeshEngine] Preprocessing meshes")
        print(f"  [MeshEngine] LOD bias: {self.lod_bias}")
        print(f"  [MeshEngine] Output: {out_dir}")

        # For PoC, we generate a synthetic sphere if no game meshes provided
        # In production, we'd iterate over .obj/.glb files in game_meshes_dir
        if not self.game_meshes_dir or not self.game_meshes_dir.exists():
            print(f"  [MeshEngine] No game meshes provided, generating synthetic test mesh")
            vertices, indices = generate_uv_sphere(radius=1.0, lat_segments=64, lon_segments=128)
        else:
            # In production: load .obj/.glb files here
            print(f"  [MeshEngine] Would process meshes from {self.game_meshes_dir} (TODO: real loader)")
            vertices, indices = generate_uv_sphere(radius=1.0, lat_segments=64, lon_segments=128)

        # Save source mesh
        write_obj(out_dir / "source.obj", vertices, indices, vertex_count=len(vertices) // 3)

        # Simplify at 4 LOD levels, with bias applied
        # lod_bias = -2 -> more aggressive (target ratios shift down)
        # lod_bias = 0 -> default (50%, 25%, 10%)
        # lod_bias = +2 -> less aggressive (target ratios shift up)
        lod_targets = [
            ("LOD0", 1.00),
            ("LOD1", max(0.05, 0.50 + self.lod_bias * 0.05)),
            ("LOD2", max(0.05, 0.25 + self.lod_bias * 0.05)),
            ("LOD3", max(0.05, 0.10 + self.lod_bias * 0.05)),
        ]

        t0 = time.perf_counter()
        options = SIMPLIFY_LOCK_BORDER  # preserve UV seams
        for name, ratio in lod_targets:
            if ratio >= 1.0:
                write_obj(out_dir / f"{name}.obj", vertices, indices,
                         vertex_count=len(vertices) // 3)
                continue
            new_idx, err, _ = simplify_mesh(vertices, indices, ratio, options=options)
            new_verts, new_idx_c, new_vc, _ = compact_and_optimize_vertex_fetch(vertices, new_idx)
            write_obj(out_dir / f"{name}.obj", new_verts, new_idx_c, vertex_count=new_vc)
        self.process_time_ms = (time.perf_counter() - t0) * 1000.0
        self.processed_count = len(lod_targets)

        print(f"  [MeshEngine] Processed {self.processed_count} LOD levels in {self.process_time_ms:.0f}ms")

    def start(self) -> None:
        super().start()
        cache = self.environment.image_fs.aurora_meshes_path()
        if cache.exists():
            obj_count = len(list(cache.glob("*.obj")))
            print(f"  [MeshEngine] Started. Cache: {obj_count} OBJ files at {cache}")
        else:
            print(f"  [MeshEngine] Started. Cache empty (run preprocess_on_install first)")
