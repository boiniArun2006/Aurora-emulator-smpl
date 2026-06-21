# Aurora Emulator — Project State

**Last updated:** 2026-06-21
**Current phase:** Phase 1 — AOT Texture Transcoder (COMPLETE)
**Next phase:** Phase 2 — Mesh Simplification Engine

---

## What is Aurora?

Aurora is a **hybrid PC-game emulator for Android** that targets mid/low-end devices, including those with Mali GPUs (which current emulators like Winlator/Mobox fail on).

**Architecture:** Wrap proven open-source components (Box64, Wine, DXVK, Turnip) with a novel orchestration layer that adds:
- AOT preprocessing pipeline (textures → ASTC, meshes → simplified, shaders → precompiled)
- Modular engines (texture, mesh, loader, world, shader)
- Mali Vulkan sanitizer shim
- Community shader cache cloud

**Repository:** `/home/z/my-project/aurora/`

---

## Phase Status

| Phase | Status | Description |
|---|---|---|
| 0 | ✅ Done | Project setup, git repo, folder structure |
| 1 | ✅ Done | AOT Texture Transcoder (Basis Universal, BCn→KTX2/UASTC→ASTC) |
| 2 | ⏳ Next | Mesh Simplification Engine (Garland-QEM) |
| 3 | Pending | Loader Engine with predictive prefetching |
| 4 | Pending | Shader cache infrastructure design |
| 5 | Pending | Orchestration layer tying engines together |
| 6 | Pending | Mali Vulkan sanitizer shim |
| 7 | Pending | Integration with Box64 + Wine + DXVK |
| 8 | Pending | Android APK wrapper |

---

## Repository Layout

```
aurora/
├── PROJECT_STATE.md          ← YOU ARE HERE — read this first in any new session
├── README.md                  ← Project overview
├── src/
│   └── texture_engine/
│       └── aot_texture_transcoder.py   ← Phase 1 PoC (working)
├── third_party/
│   └── basis_universal/       ← Binomial LLC, built — bin/basisu CLI works
├── tests/
│   ├── texture_engine_input/  ← Generated synthetic test textures
│   └── texture_engine_output/ ← KTX2/ASTC outputs + pipeline_results.json
├── docs/                      ← Research briefs and design docs
├── scripts/                   ← Setup and utility scripts
└── assets/                    ← Static assets
```

---

## Phase 1 — What's Built

### Component: `src/texture_engine/aot_texture_transcoder.py`

A Python module implementing the AOT texture preprocessing pipeline:

1. **Input:** PNG/JPG/TGA/QOI/DDS/EXR/HDR source textures (PC game format)
2. **AOT step (on install):** Encodes source → KTX2 container with UASTC codec, supercompressed with Zstd. Generates mipmaps. Quality is configurable (fast/default/max).
3. **On-device step (at load time):** Transcodes KTX2/UASTC → ASTC 4x4 (mobile GPU native format). On real device, this is a library call to `basisu_transcoder.cpp` (single-file, no deps), NOT a subprocess.
4. **Output:** `.ktx2` (storage format on device), `.astc` (transcoded at load), `pipeline_results.json` (timing & size metrics).

### Validated by PoC test

Ran on 3 synthetic textures (1024×1024 UI atlas, 1024×1024 gradient skybox, 512×512 noise normal map):

- **9.70x compression** vs raw RGBA (4 MB raw → 411 KB KTX2/UASTC shipped)
- AOT encode: ~3 sec per 1024×1024 texture (one-time cost on install, acceptable)
- Transcode (PoC mode, subprocess + all formats): ~1 sec per texture
  - Production transcode (library call, ASTC only) would be **microseconds per block**

### How to run

```bash
cd /home/z/my-project/aurora
python3 src/texture_engine/aot_texture_transcoder.py test --quality fast
# Outputs in tests/texture_engine_output/
```

### Dependencies installed

- `Basis Universal v2.10` (built from source at `third_party/basis_universal/`, Apache 2.0 license)
- `Pillow` Python package (for synthetic test texture generation)
- `cmake` (installed via pip)
- `g++ 14.2` (system)

---

## Next Session — Where to Pick Up

### Phase 2: Mesh Simplification Engine

**Goal:** Build a mesh simplification engine that uses Garland & Heckbert's Quadric Error Metrics (QEM) algorithm to AOT-simplify game meshes for low-end targets.

**Algorithm reference:** Garland & Heckbert 1997, "Surface Simplification Using Quadric Error Metrics" (https://www.cs.cmu.edu/~garland/Papers/quadrics.pdf)

**Reference implementations to study:**
- CGAL's `Surface_mesh_simplification` package (C++, well-documented, follows the paper closely)
- Henrik Rydgård's mesh simplification in PPSSPP
- `meshoptimizer` library by Arseny Kapoulkine (has simplifier)

**Plan for Phase 2:**
1. Add `meshoptimizer` library to `third_party/` (Apache 2.0, used by AAA games)
2. Build `src/mesh_engine/aot_mesh_simplifier.py` that:
   - Loads OBJ/PLY/glTF meshes (typical PC game mesh formats)
   - Runs simplification at multiple LOD levels (100%, 70%, 50%, 30%)
   - Outputs LOD set as a single file (e.g., .glb with multiple meshes)
3. PoC test: generate a synthetic mesh (e.g., subdivided sphere), simplify at multiple levels, verify visual quality & timing
4. Document results in worklog

**First step:** Read `meshoptimizer` source at https://github.com/zeux/meshoptimizer — specifically `simplifier.cpp`. Verify it follows QEM (it does, with extensions for attributes).

---

## How to Continue in a New Session

1. **Read this file first** (`/home/z/my-project/aurora/PROJECT_STATE.md`)
2. **Read the worklog** (`/home/z/my-project/aurora/worklog.md`) — chronological log of every session
3. **Check git log** for commit history: `cd /home/z/my-project/aurora && git log --oneline`
4. **Pick up at "Next Session" section above**

---

## Build & Run Quick Reference

```bash
# Run Phase 1 PoC test
cd /home/z/my-project/aurora
python3 src/texture_engine/aot_texture_transcoder.py test --quality fast

# Process a directory of real textures
python3 src/texture_engine/aot_texture_transcoder.py process <input_dir> <output_dir> --quality default

# Verify basisu binary still exists
ls -la third_party/basis_universal/bin/basisu

# If basisu is missing, rebuild:
cd third_party/basis_universal
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

---

## Research & Decisions Log

See `docs/research_synthesis.md` for the full research brief that informed the architecture. Key decisions:

1. **Use Basis Universal** for texture transcoding (not custom encoder) — Binomial's library is 8+ years of work, well-validated, supports BCn↔ASTC↔ETC2↔PVRTC
2. **Use KTX2/UASTC as the on-device storage format** — supercompressed with Zstd, transcodable to any GPU format in microseconds
3. **Use ASTC 4x4 LDR as the runtime GPU format** — universally supported on Mali-G610+ and Adreno 6xx+
4. **Use Box64/FEX-Emu as CPU translator** (don't reinvent) — fork & extend with AOT mode
5. **Use DXVK as D3D→Vulkan translator** (don't reinvent) — fork & extend with Mali sanitizer
6. **Modular engine architecture** (user's idea) — validated by RetroArch's libretro pattern

---

## Persistence Notes

- Project lives at `/home/z/my-project/aurora/` — persistent across sessions
- Git repo initialized — every change committed
- `PROJECT_STATE.md` (this file) is the handoff document — always update at end of session
- `worklog.md` is the chronological log — append new entries, never overwrite
- For external backup: clone to user's machine, or push to private GitHub repo (TBD)
