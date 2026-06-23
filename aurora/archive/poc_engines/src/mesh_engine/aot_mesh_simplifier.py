#!/usr/bin/env python3
"""
Aurora Emulator - Phase 2: AOT Mesh Simplifier
================================================

Implements the "Mesh Engine" of Aurora's AOT preprocessing pipeline.
Uses meshoptimizer's QEM-based simplifier (Arseny Kapoulkine, MIT license,
pinned to v1.1).

Algorithm reference:
    Garland, M. and Heckbert, P. S. 1997.
    "Surface Simplification Using Quadric Error Metrics."
    Proceedings of the 24th Annual Conference on Computer Graphics.
    https://www.cs.cmu.edu/~garland/Papers/quadrics.pdf

meshoptimizer extends classical QEM with:
    - Attribute-aware error metric (normals, UVs, colors)
    - Lockable vertices (preserve boundary/seams)
    - Topology-preserving edge collapses

Pipeline:
    PC game ships with .obj / .glb / .fbx meshes (full LOD0 detail)
        |
        |  [AOT preprocessing - done ONCE on install]
        v
    Simplify mesh at multiple LOD levels (100%, 70%, 50%, 30%, 10%)
        |
        v
    Save each LOD as .obj (portable, well-supported)
        |
        |  [Runtime on device - pick LOD based on distance/screen size]
        v
    Upload appropriate LOD to GPU

This script is a PoC: generates a synthetic high-poly sphere,
simplifies at 4 LOD levels, saves each LOD as .obj, reports metrics.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import sys
import time
from ctypes import c_float, c_size_t, c_uint, POINTER
from dataclasses import dataclass, asdict
from pathlib import Path

# =============================================================================
# Locate meshoptimizer shared library (cross-platform)
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Pick the correct shared library extension for the current OS.
# Linux: .so, macOS: .dylib, Windows: .dll
if sys.platform == "darwin":
    _LIB_EXT = ".dylib"
elif sys.platform == "win32":
    _LIB_EXT = ".dll"
else:
    _LIB_EXT = ".so"

# meshoptimizer CMakeLists.txt produces:
#   Linux/macOS: libmeshoptimizer.{so,dylib}
#   Windows:     meshoptimizer.dll (no "lib" prefix on Windows)
_LIB_BASENAME = "libmeshoptimizer" if sys.platform != "win32" else "meshoptimizer"
MESHOPT_LIB = PROJECT_ROOT / "third_party" / "meshoptimizer" / "build" / f"{_LIB_BASENAME}{_LIB_EXT}"

if not MESHOPT_LIB.exists():
    raise FileNotFoundError(
        f"meshoptimizer shared library not found at {MESHOPT_LIB}.\n"
        f"Expected platform: {sys.platform} (extension {_LIB_EXT})\n"
        f"Build it with: bash scripts/setup_third_party.sh\n"
        f"Or manually: cd third_party/meshoptimizer && mkdir build && cd build && "
        f"cmake .. -DCMAKE_BUILD_TYPE=Release -DMESHOPT_BUILD_SHARED_LIBS=ON && "
        f"cmake --build . --config Release -j"
    )

# Load the shared library with a helpful error message if it fails
# (e.g. wrong architecture, missing system deps, ABI mismatch).
try:
    _lib = ctypes.CDLL(str(MESHOPT_LIB))
except OSError as e:
    raise RuntimeError(
        f"Failed to load meshoptimizer shared library at {MESHOPT_LIB}.\n"
        f"This usually means: (1) wrong architecture (e.g. built for x86_64 "
        f"on an ARM host), (2) missing system runtime (e.g. libstdc++), "
        f"or (3) ABI mismatch after a pinned-version bump.\n"
        f"Try rebuilding with: bash scripts/setup_third_party.sh\n"
        f"Underlying error: {e}"
    ) from e

# Vertex layout constants. meshopt_simplify REQUIRES positions to be the first
# 12 bytes of each vertex (3 floats x 4 bytes). If you add attributes (UVs,
# normals, colors), they go AFTER positions and you must update the stride.
# We use position-only vertices in the PoC, so stride = 12 bytes.
VERTEX_STRIDE_BYTES = 12  # 3 floats (x, y, z) x 4 bytes each

# ---- Simplification options (from meshoptimizer.h) --------------------------
# These are bitmask flags. We expose them so callers can pick the right
# tradeoffs per mesh type (e.g. lock border for UV-seamed game meshes).
SIMPLIFY_LOCK_BORDER = 1 << 0       # Preserve topological border (UV seams)
SIMPLIFY_SPARSE = 1 << 1            # Input is a sparse subset
SIMPLIFY_ERROR_ABSOLUTE = 1 << 2    # Error is absolute, not relative to mesh extents
SIMPLIFY_PRUNE = 1 << 3             # Remove disconnected parts
SIMPLIFY_REGULARIZE = 1 << 4        # More regular triangle shapes (costs quality)

# ---- Function signatures (from meshoptimizer.h) -----------------------------
# size_t meshopt_simplify(
#     unsigned int* destination,
#     const unsigned int* indices, size_t index_count,
#     const float* vertex_positions, size_t vertex_count, size_t vertex_positions_stride,
#     size_t target_index_count, float target_error,
#     unsigned int options, float* result_error);
_lib.meshopt_simplify.argtypes = [
    POINTER(c_uint),                          # destination
    POINTER(c_uint), c_size_t,                # indices, index_count
    POINTER(c_float), c_size_t, c_size_t,     # vertices, vertex_count, stride
    c_size_t, c_float,                        # target_index_count, target_error
    c_uint, POINTER(c_float),                 # options, result_error
]
_lib.meshopt_simplify.restype = c_size_t

# void meshopt_optimizeVertexFetch(
#     void* destination,
#     unsigned int* indices, size_t index_count,
#     const void* vertices, size_t vertex_count, size_t vertex_size);
# IMPORTANT: This reorders vertices into `destination` AND rewrites `indices`
# in place. The resulting indices reference the new vertex order, NOT the
# original. Callers MUST use the destination buffer, not the source.
_lib.meshopt_optimizeVertexFetch.argtypes = [
    ctypes.c_void_p,
    POINTER(c_uint), c_size_t,
    ctypes.c_void_p, c_size_t, c_size_t,
]
_lib.meshopt_optimizeVertexFetch.restype = None


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class LODResult:
    """Result of simplifying a mesh to one LOD level."""
    lod_name: str
    target_ratio: float                 # requested triangle ratio
    actual_index_count: int             # actual triangles * 3 after simplification
    actual_triangle_count: int
    actual_vertex_count: int            # vertices after compaction (NEW)
    target_error: float                 # requested error threshold
    result_error: float                 # actual error achieved
    simplify_time_ms: float
    vertex_fetch_optimize_ms: float
    obj_file: str = ""                  # path to saved .obj (NEW)


@dataclass
class MeshResult:
    source_triangle_count: int
    source_vertex_count: int
    lods: list


# =============================================================================
# Synthetic test mesh: UV sphere (deterministic, no external deps)
# =============================================================================

def generate_uv_sphere(radius: float = 1.0,
                       lat_segments: int = 64,
                       lon_segments: int = 128) -> tuple[list[float], list[int]]:
    """Generate a UV sphere as (vertices, indices).
    vertices: flat list of floats, 3 per vertex (x,y,z position only).
    """
    if lat_segments < 2 or lon_segments < 3:
        raise ValueError(f"lat_segments>=2 and lon_segments>=3 required, got {lat_segments}/{lon_segments}")
    if radius <= 0:
        raise ValueError(f"radius must be positive, got {radius}")

    vertices: list[float] = []
    indices: list[int] = []

    for lat in range(lat_segments + 1):
        theta = math.pi * lat / lat_segments  # 0 .. pi
        sin_t = math.sin(theta)
        cos_t = math.cos(theta)
        for lon in range(lon_segments + 1):
            phi = 2 * math.pi * lon / lon_segments  # 0 .. 2pi
            sin_p = math.sin(phi)
            cos_p = math.cos(phi)
            x = radius * sin_t * cos_p
            y = radius * cos_t
            z = radius * sin_t * sin_p
            vertices.extend([x, y, z])

    def v(lat: int, lon: int) -> int:
        return lat * (lon_segments + 1) + lon

    for lat in range(lat_segments):
        for lon in range(lon_segments):
            a = v(lat, lon)
            b = v(lat + 1, lon)
            c = v(lat + 1, lon + 1)
            d = v(lat, lon + 1)
            indices.extend([a, b, d])
            indices.extend([b, c, d])

    return vertices, indices


# =============================================================================
# Simplification
# =============================================================================

def simplify_mesh(
    vertices: list[float],
    indices: list[int],
    target_ratio: float,
    target_error: float = 0.01,
    options: int = 0,
) -> tuple[list[int], float, float]:
    """
    Simplify a mesh to target_ratio of its original triangle count.
    Returns (new_indices, result_error, time_ms).

    Notes on `options`:
        - For game meshes with UV seams: pass SIMPLIFY_LOCK_BORDER
        - For sparse subset meshes: pass SIMPLIFY_SPARSE
        - 0 = safe default (topology preserved, no special handling)
    """
    if not vertices:
        raise ValueError("vertices list is empty")
    if not indices:
        raise ValueError("indices list is empty")
    if len(vertices) % 3 != 0:
        raise ValueError(f"vertices list length {len(vertices)} is not a multiple of 3")
    if len(indices) % 3 != 0:
        raise ValueError(f"indices list length {len(indices)} is not a multiple of 3")
    if not (0.0 < target_ratio < 1.0):
        raise ValueError(f"target_ratio must be in (0, 1), got {target_ratio}")
    if not (0.0 <= target_error <= 1.0):
        raise ValueError(f"target_error must be in [0, 1], got {target_error}")

    index_count = len(indices)
    vertex_count = len(vertices) // 3

    # Validate that all indices reference real vertices.
    # Without this check, an out-of-bounds index silently corrupts the mesh
    # (meshopt will read past the vertex buffer or write garbage indices).
    max_index = max(indices)
    if max_index >= vertex_count:
        raise ValueError(
            f"Index {max_index} is out of bounds for vertex buffer of size "
            f"{vertex_count} (vertices have indices 0..{vertex_count - 1}). "
            f"This usually means the vertex buffer was truncated or the indices "
            f"were generated for a different mesh."
        )
    # Also validate non-negative (defensive - shouldn't happen with int inputs
    # but cheap to check)
    min_index = min(indices)
    if min_index < 0:
        raise ValueError(f"Negative index {min_index} found in indices list")

    # Convert to ctypes
    src_indices = (c_uint * index_count)(*indices)
    src_vertices = (c_float * len(vertices))(*vertices)
    # Per meshopt docs: destination must hold up to index_count (NOT target_index_count)
    dst_indices = (c_uint * index_count)()
    result_error = c_float(0.0)

    target_index_count = max(3, int(index_count * target_ratio))

    t0 = time.perf_counter()
    actual = _lib.meshopt_simplify(
        dst_indices,
        src_indices, index_count,
        src_vertices, vertex_count, VERTEX_STRIDE_BYTES,
        target_index_count, target_error,
        options,
        ctypes.byref(result_error),
    )
    t1 = time.perf_counter()

    if actual == 0:
        raise RuntimeError("meshopt_simplify returned 0 indices - simplification failed completely")

    new_indices = list(dst_indices[:actual])
    return new_indices, result_error.value, (t1 - t0) * 1000.0


def compact_and_optimize_vertex_fetch(
    vertices: list[float],
    indices: list[int],
) -> tuple[list[float], list[int], int, float]:
    """
    Run meshopt_optimizeVertexFetch to:
      1. Reorder vertices for GPU cache efficiency
      2. Compact the vertex buffer (remove unused vertices after simplification)

    Returns (new_vertices, new_indices, new_vertex_count, time_ms).

    BUGFIX: Previously this function discarded the destination vertex buffer
    and only returned timing. The C function reorders vertices into the
    destination buffer AND rewrites indices in place; we MUST use the new
    vertex buffer, not the original. Otherwise indices reference vertices
    that don't exist in the array we pass downstream.
    """
    if not vertices or not indices:
        raise ValueError("vertices and indices must be non-empty")
    if len(vertices) % 3 != 0:
        raise ValueError("vertices length must be a multiple of 3")

    index_count = len(indices)
    vertex_count = len(vertices) // 3

    # Validate indices are in-bounds. After simplify_mesh() this should always
    # be true, but compact_and_optimize_vertex_fetch can also be called on
    # raw user input, so we validate here too.
    max_index = max(indices)
    if max_index >= vertex_count:
        raise ValueError(
            f"Index {max_index} out of bounds for vertex buffer of size {vertex_count}"
        )

    # Allocate mutable ctypes buffers. We need separate src and dst because
    # optimizeVertexFetch reads from src and writes to dst.
    src_indices = (c_uint * index_count)(*indices)
    src_vertices = (c_float * len(vertices))(*vertices)
    dst_vertices = (c_float * len(vertices))()

    t0 = time.perf_counter()
    _lib.meshopt_optimizeVertexFetch(
        dst_vertices,
        src_indices, index_count,             # indices rewritten in place
        src_vertices, vertex_count, VERTEX_STRIDE_BYTES,
    )
    t1 = time.perf_counter()

    # The new indices (rewritten in place) reference the new vertex order.
    new_indices = list(src_indices[:index_count])
    new_vertices = list(dst_vertices[:len(vertices)])

    # Count distinct vertices actually used (post-compaction)
    used = set(new_indices)
    new_vertex_count = len(used)

    return new_vertices, new_indices, new_vertex_count, (t1 - t0) * 1000.0


# =============================================================================
# OBJ writer (simple, well-supported format for PoC verification)
# =============================================================================

def write_obj(path: Path, vertices: list[float], indices: list[int],
              vertex_count: int | None = None) -> None:
    """Write a mesh to a Wavefront .obj file. Positions only (no normals/UVs).
    This is enough for PoC verification - real game meshes would use .glb.

    If `vertex_count` is provided, only the first N vertices are written
    (used after compaction, where the vertex buffer is over-allocated).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    n = vertex_count if vertex_count is not None else len(vertices) // 3
    if n * 3 > len(vertices):
        raise ValueError(f"vertex_count {n} exceeds buffer size {len(vertices) // 3}")
    with path.open("w") as f:
        f.write(f"# Aurora AOT Mesh Simplifier output\n")
        f.write(f"# vertices: {n}, triangles: {len(indices) // 3}\n")
        # Vertices (1-indexed in OBJ)
        for i in range(n):
            x, y, z = vertices[i*3], vertices[i*3+1], vertices[i*3+2]
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        # Faces (OBJ is 1-indexed)
        for i in range(0, len(indices), 3):
            a, b, c = indices[i] + 1, indices[i+1] + 1, indices[i+2] + 1
            f.write(f"f {a} {b} {c}\n")


# =============================================================================
# PoC test
# =============================================================================

def run_poc(output_dir: Path, lock_border: bool = False):
    print("=== Aurora Emulator - Phase 2 PoC: AOT Mesh Simplifier ===\n")

    # Generate high-poly sphere (typical PC-game hero-asset density)
    print("[1/3] Generating synthetic UV sphere (lat=64, lon=128) ...")
    vertices, indices = generate_uv_sphere(radius=1.0, lat_segments=64, lon_segments=128)
    src_tris = len(indices) // 3
    src_verts = len(vertices) // 3
    print(f"      Vertices: {src_verts:,}")
    print(f"      Triangles: {src_tris:,}")

    # Save source mesh as OBJ for reference
    output_dir.mkdir(parents=True, exist_ok=True)
    write_obj(output_dir / "source.obj", vertices, indices, vertex_count=src_verts)
    print(f"      Saved source: {output_dir / 'source.obj'}")

    # Simplification options
    options = SIMPLIFY_LOCK_BORDER if lock_border else 0
    if lock_border:
        print(f"      [option] SIMPLIFY_LOCK_BORDER enabled (preserves UV seams)")

    # Simplify at 4 LOD levels (typical game LOD chain)
    print(f"\n[2/3] Simplifying to 4 LOD levels (QEM via meshoptimizer) ...")
    lods: list[LODResult] = []
    lod_targets = [
        ("LOD0", 1.00),  # original (no simplification)
        ("LOD1", 0.50),  # 50% of triangles
        ("LOD2", 0.25),  # 25% of triangles
        ("LOD3", 0.10),  # 10% of triangles (mobile low-end target)
    ]
    for name, ratio in lod_targets:
        if ratio >= 1.0:
            # LOD0: just save the original, no processing
            obj_path = output_dir / f"{name}.obj"
            write_obj(obj_path, vertices, indices, vertex_count=src_verts)
            lods.append(LODResult(
                lod_name=name, target_ratio=ratio,
                actual_index_count=len(indices), actual_triangle_count=src_tris,
                actual_vertex_count=src_verts,
                target_error=0.0, result_error=0.0,
                simplify_time_ms=0.0, vertex_fetch_optimize_ms=0.0,
                obj_file=str(obj_path),
            ))
            print(f"  {name}: {src_tris:,} tris / {src_verts:,} verts (no simplification)")
            continue

        new_idx, err, simplify_ms = simplify_mesh(
            vertices, indices, ratio,
            target_error=0.01,
            options=options,
        )
        # Compact + optimize vertex fetch (BUGFIX: now we actually use the result)
        new_verts, new_idx_compact, new_vert_count, vfo_ms = compact_and_optimize_vertex_fetch(
            vertices, new_idx
        )
        actual_tris = len(new_idx_compact) // 3

        # Save LOD mesh
        obj_path = output_dir / f"{name}.obj"
        write_obj(obj_path, new_verts, new_idx_compact, vertex_count=new_vert_count)

        lods.append(LODResult(
            lod_name=name, target_ratio=ratio,
            actual_index_count=len(new_idx_compact), actual_triangle_count=actual_tris,
            actual_vertex_count=new_vert_count,
            target_error=0.01, result_error=err,
            simplify_time_ms=simplify_ms, vertex_fetch_optimize_ms=vfo_ms,
            obj_file=str(obj_path),
        ))
        print(f"  {name}: target={int(ratio*100)}% -> {actual_tris:,} tris / "
              f"{new_vert_count:,} verts "
              f"(err={err:.4f}, simplify={simplify_ms:.1f}ms, vfo={vfo_ms:.1f}ms)")
        print(f"        Saved: {obj_path}")

    # Summary
    print(f"\n[3/3] Summary:")
    print(f"  Source:  {src_tris:>8,} triangles, {src_verts:>8,} vertices")
    for lod in lods:
        if lod.target_ratio >= 1.0:
            continue
        tri_ratio = lod.actual_triangle_count / src_tris
        vert_ratio = lod.actual_vertex_count / src_verts
        print(f"  {lod.lod_name}: {lod.actual_triangle_count:>8,} tris  "
              f"({tri_ratio*100:5.1f}% of src)  "
              f"{lod.actual_vertex_count:>8,} verts ({vert_ratio*100:5.1f}% of src)  "
              f"err={lod.result_error:.4f}")

    print(f"\n  NOTE: On a real device, the appropriate LOD is selected at runtime")
    print(f"  based on screen-space size (distance from camera). Meshopt's QEM")
    print(f"  preserves appearance to the target_error threshold (0.01 = 1% deformation).")

    # Write results JSON
    result = MeshResult(
        source_triangle_count=src_tris,
        source_vertex_count=src_verts,
        lods=[asdict(l) for l in lods],
    )
    out_path = output_dir / "mesh_pipeline_results.json"
    out_path.write_text(json.dumps(asdict(result), indent=2))
    print(f"\nResults JSON: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Aurora Emulator - AOT Mesh Simplifier (Phase 2 PoC)")
    parser.add_argument("--output_dir", type=Path,
                        default=PROJECT_ROOT / "tests" / "mesh_engine_output")
    parser.add_argument("--lock_border", action="store_true",
                        help="Use SIMPLIFY_LOCK_BORDER option (preserves UV seams)")
    args = parser.parse_args()
    run_poc(args.output_dir, lock_border=args.lock_border)


if __name__ == "__main__":
    main()
