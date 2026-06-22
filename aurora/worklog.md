# Aurora Emulator — Worklog

This is the chronological log of every work session on the Aurora emulator project.
Append new entries at the bottom — never overwrite existing entries.

---
Task ID: 0
Agent: Main (Super Z)
Session: 2026-06-21
Task: Project setup and Phase 1 (AOT Texture Transcoder) implementation

Work Log:
- Created project structure at /home/z/my-project/aurora/ with subdirectories (src, third_party, tests, docs, scripts, assets, download)
- Initialized git repo on `main` branch
- Installed build dependencies: cmake (via pip), g++ 14.2 (system), Pillow (Python)
- Cloned Basis Universal v2.10 from https://github.com/BinomialLLC/basis_universal to third_party/
- Built basisu CLI tool with cmake + make (Release config, no SSE, with Zstd)
  - Binary at: third_party/basis_universal/bin/basisu
  - Library at: third_party/basis_universal/build/libbasisu_encoder.a
- Wrote Phase 1 PoC: src/texture_engine/aot_texture_transcoder.py
  - Encodes source textures (PNG/DDS/etc) to KTX2 container with UASTC codec + Zstd supercompression
  - Transcodes KTX2/UASTC to ASTC 4x4 (mobile GPU native format)
  - Reports timing, sizes, compression ratios
  - Includes synthetic test texture generator (UI atlas, gradient skybox, noise normal map)
- Hit two CLI flag issues with basisu (v2.10 renamed some flags):
  - `-ktx2_uastc_supercompression zstd` → use `-ktx2_zstandard_level 9` (zstd is on by default)
  - `-format ASTC` in unpack mode doesn't exist — `-unpack` produces ALL formats (BC1/BC3/BC7/ETC1/ETC2/PVRTC/ASTC) at once
- Fixed both issues, PoC now runs end-to-end successfully
- Validated with 3 synthetic textures:
  - 9.70x compression vs raw RGBA (4 MB raw → 411 KB KTX2/UASTC shipped)
  - AOT encode: ~3 sec per 1024x1024 texture (one-time install cost, acceptable)
  - Transcode (PoC mode, subprocess + all formats): ~1 sec per texture
    - Production would be library call (basisu_transcoder.cpp, single-file, no deps) running in microseconds per block

Stage Summary:
- Phase 1 PoC complete and validated. The AOT texture transcoder pipeline works end-to-end.
- Key insight: KTX2/UASTC is the right on-device storage format (supercompressed with Zstd, transcodable to any GPU format). ASTC 4x4 is the right runtime GPU format (universal on modern Mali/Adreno).
- Next: Phase 2 — Mesh Simplification Engine using Garland-QEM. Will use `meshoptimizer` library (Arseny Kapoulkine, MIT license, used by AAA games, follows QEM with extensions).

---
Task ID: aurora-phase-1.5
Agent: Main (Super Z)
Session: 2026-06-22
Task: Add GitHub Actions CI workflow to auto-validate the setup script + Phase 1 PoC on every push

Work Log:
- Created .github/workflows/ci.yml with 9 steps:
  1. Checkout repo
  2. Install build deps (cmake, python3, Pillow) via apt + pip
  3. Cache basis_universal source (keyed on MANIFEST.txt hash)
  4. Cache basis_universal build artifacts (keyed on MANIFEST.txt + setup script hash)
  5. Run scripts/setup_third_party.sh
  6. Verify basisu binary exists and runs
  7. Run Phase 1 PoC (aot_texture_transcoder.py test --quality fast)
  8. Verify 3 KTX2 + 3 ASTC files produced
  9. Upload pipeline_results.json as artifact (14-day retention)
- Hardened scripts/setup_third_party.sh:
  - Auto-locates cmake (PATH, then ~/.venv/bin, then ~/.local/bin) — works on CI runners AND dev containers
  - Skips basis_universal rebuild if bin/basisu already exists — respects CI cache hits
- Made src/texture_engine/aot_texture_transcoder.py portable:
  - Default test paths now computed relative to script location (was hardcoded to /home/z/my-project/aurora/tests/...)
  - This was breaking CI on GitHub runners
- Simulated full CI run locally by copying repo to /tmp/aurora-ci-test/ — all steps passed
- Committed (commit 68f1a8e) and pushed to GitHub
- CI ran on GitHub Actions: PASSED in 2 minutes 17 seconds (all 14 steps green)
  - URL: https://github.com/boiniArun2006/Aurora-emulator-smpl/actions/runs/27926230747
- Updated PROJECT_STATE.md with CI badge and phase 1.5 entry

Stage Summary:
- Aurora now has CI. Every push to main (and every PR) will automatically:
  - Install deps on a clean Ubuntu 22.04 runner
  - Clone & build Basis Universal from source
  - Run the Phase 1 PoC test
  - Verify outputs are produced
- Cache should make subsequent runs ~30 seconds instead of 2+ minutes
- Next: Phase 2 — Mesh Simplification Engine (Garland-QEM via meshoptimizer)

---
Task ID: aurora-phase-2
Agent: Main (Super Z)
Session: 2026-06-22
Task: Build Phase 2 — AOT Mesh Simplifier using meshoptimizer's QEM implementation

Work Log:
- Cloned meshoptimizer (Arseny Kapoulkine, MIT license, used by AAA games) to third_party/
- Built as shared library (libmeshoptimizer.so) for Python ctypes bindings
  - cmake config: -DMESHOPT_BUILD_SHARED_LIBS=ON
  - Located at: third_party/meshoptimizer/build/libmeshoptimizer.so
- Wrote Phase 2 component: src/mesh_engine/aot_mesh_simplifier.py
  - ctypes bridge to meshopt_simplify() and meshopt_optimizeVertexFetch()
  - Generates synthetic UV sphere (8,385 verts, 16,384 tris — typical hero-asset density)
  - Simplifies to 4 LOD levels: LOD0 (100%), LOD1 (50%), LOD2 (25%), LOD3 (10%)
  - Reports triangle counts, error, and timing per LOD
- Updated scripts/setup_third_party.sh: now also builds meshoptimizer
- Updated .github/workflows/ci.yml: caches meshoptimizer source+build, verifies .so, runs Phase 2 PoC, validates 4+ LODs in output JSON
- Validated locally: 16k triangles → 1.6k triangles in ~5ms with 0.34% error (QEM works as advertised)

Stage Summary:
- Phase 2 PoC complete and validated. meshoptimizer's QEM implementation produces 4 LOD levels with sub-1% deformation error in single-digit milliseconds.
- Next: Phase 3 — Loader Engine with predictive prefetching (Patterson's Informed Prefetching + Markov models).

---
Task ID: aurora-audit-1
Agent: Main (Super Z)
Session: 2026-06-22
Task: Audit third-party code + our wrappers for bugs/issues, fix them, pin versions

Work Log:
- Audited third-party:
  - basis_universal v2_1_0r: 3 open bug issues. Issue #271 (Android API<24 ftello) is a blocker
    for our Android porting — documented in third_party/patches/README.md with patch to apply
    when we cross-compile. Issues #257, #259 are minor and don't affect our use case.
  - meshoptimizer v1.1: 0 open bug issues, source clean (no TODO/FIXME/HACK in simplifier.cpp)
- Pinned both libs to specific release tags in MANIFEST.txt:
  - basis_universal: v2_1_0r (commit e4f439fc)
  - meshoptimizer: v1.1 (commit dc9d09ed)
- Updated setup_third_party.sh to use `git clone --branch <ref>` (cleaner than fetch+checkout)
- Fixed 4 bugs in src/mesh_engine/aot_mesh_simplifier.py:
  1. **CRITICAL: optimize_vertex_fetch discarded its result** — was passing dst_vertices but
     never using it. The function reorders vertices AND rewrites indices in place; we lost both.
     Renamed to compact_and_optimize_vertex_fetch(), now returns (new_vertices, new_indices,
     new_vertex_count, time_ms).
  2. **LODs weren't saved to disk** — only JSON metadata. Now saves each LOD as .obj for
     verification + downstream use.
  3. **OBJ files had full vertex buffer** — write_obj now accepts vertex_count parameter and
     only writes the first N (used) vertices.
  4. **No input validation** — added validation for vertices/indices lengths, target_ratio,
     target_error, mesh dimensions.
- Added meshopt_SimplifyLockBorder support (--lock_border flag) for UV-seamed game meshes
- Fixed 4 bugs in src/texture_engine/aot_texture_transcoder.py:
  1. **CRITICAL: -no_multithreading was always on** — this slowed encoding ~3x for
     "deterministic benchmarking". Made it opt-in via single_threaded=False default.
     Production encoding is now 3x faster.
  2. **No cleanup on failure** — transcode_to_astc used try/finally so temp dirs always
     cleaned up, even on subprocess failure.
  3. **No input validation** — added validation for quality, astc_block_size, source file
     existence, supported extensions.
  4. **ASTC block size was hardcoded** — now configurable via constructor.
- Validated all fixes:
  - Phase 1 encode: 10482ms -> 3283ms (3.2x speedup from removing -no_multithreading)
  - Phase 2 LOD OBJ files: now have correct compacted vertex counts (was 8385 for all,
    now matches actual_vertex_count per LOD)
  - Input validation: all 8 negative tests pass
  - --lock_border flag: works as expected (preserves border vertices)

Stage Summary:
- All identified bugs fixed and tested. Third-party libs pinned to specific release tags
  for reproducibility. basis_universal Android API<24 issue documented for future porting.
- Next: wait for user signal to start Phase 3 (Loader Engine with predictive prefetching).

---
Task ID: aurora-audit-2-claude-review
Agent: Main (Super Z)
Session: 2026-06-22
Task: Address Claude's code review findings (12 issues), verify each against actual code, fix the real ones

Work Log:
- Got external code review from Claude via GitHub Copilot share (12 issues identified)
- Audited each of Claude's 12 findings against current code:
  - 10/12 CORRECT, 1/12 WRONG (#7: per-call ASTC validation already exists at line 239), 1/12 minor
- Fixed all real issues:
  - #1: Cross-platform library paths (.so/.dylib/.dll) and basisu.exe on Windows
  - #2: _compute_raw_rgba_bytes no longer silently returns wrong estimates - raises RuntimeError
    with clear message instead. Multipliers (32 for DDS, 4 for PNG) were wildly wrong.
  - #3: ctypes.CDLL wrapped in try/except OSError -> RuntimeError with diagnostic message
  - #4: Replaced hardcoded stride=12 with VERTEX_STRIDE_BYTES constant
  - #5: Added out-of-bounds index validation in both simplify_mesh AND
    compact_and_optimize_vertex_fetch. Validates max(indices) < vertex_count and min >= 0.
  - #6: Replaced ignore_errors=True with try/except OSError + warning to stderr
  - #8: Added --single-branch to git clone (was just --depth 1 --branch)
  - #9: Added CMake version check (>=3.15 required for basis_universal cxx_std_17)
    Uses sort -V for proper version comparison
  - #10: Added compression ratio sanity check - warns to stderr if KTX2 > raw RGBA
  - #11: Removed unused 'field' import from aot_mesh_simplifier.py
  - #12: Restored README.md (was 1 line, lost in earlier rebase conflict resolution).
    Now 8100+ bytes with full architecture, install instructions, status, etc.
- Skipped #7 (Claude was wrong - per-call validation already exists)
- Verified all fixes:
  - Out-of-bounds index correctly rejected (3 negative tests pass)
  - field import removed (verified via grep)
  - All 6 source-code checks pass (cross-platform paths, CDLL handling, CMake check, etc.)
  - Full CI simulation (clean /tmp copy): both PoCs pass, 3 KTX2 + 3 ASTC + 5 OBJ produced

Stage Summary:
- All 11 valid issues from Claude's review fixed and verified. README restored. Cross-platform
  support added (Linux/macOS/Windows). Input validation hardened (out-of-bounds indices).
- Lesson learned: should have caught these in my own audit. Will be more thorough next time.
- Next: wait for user signal to start Phase 3.

---
Task ID: aurora-phase-3
Agent: Main (Super Z)
Session: 2026-06-22
Task: Build Phase 3 — Loader Engine with Markov-based predictive prefetching

Work Log:
- Downloaded real CC0 test assets for cross-engine validation:
  - 4 Kodak test PNGs (kodim01-04, standard image-compression benchmark) from basis_universal/test_files
  - 2 glTF sample meshes (Box, Duck) from Khronos glTF-Sample-Models (CC0)
- Tested Phase 1 with real photos: 3.2-4.2x compression vs raw RGBA (consistent with synthetic test)
- Built Phase 3 component: src/loader_engine/predictive_prefetcher.py
  - Implements Patterson 1995 "Informed Prefetching" architecture
  - Markov chain model: transitions[file_a][file_b] = count, trained from play traces
  - Separate prefetch buffer (CRITICAL fix - initially prefetched into main cache,
    which caused cache pollution and HURT performance by -3pp)
  - LRU main cache + LRU prefetch buffer, each cache_size files
  - Predictions only above threshold (default 0.30) to avoid noise
- Built synthetic play trace generator with REALISTIC patterns (not uniform random):
  - 50% sequential scans (texture atlas streaming)
  - 25% spatial chunk patterns (player movement)
  - 15% event sequences (combat/audio)
  - 10% random (autosaves, rare events)
- Validated across 4 cache sizes (8, 16, 32, 64 files):
  - Cache=8:  15% -> 58% hit rate (+43pp, 84% prefetch accuracy)
  - Cache=16: 37% -> 74% hit rate (+37pp, 75% accuracy)
  - Cache=32: 76% -> 85% hit rate (+9pp, 45% accuracy)
  - Cache=64: 76% -> 85% hit rate (+9pp, 45% accuracy)
- Matches Patterson 1995 finding: prefetching helps most when cache << working set
- Model size: 15KB JSON (small enough to load at game start)
- Training time: <1ms for 400-access trace

Key bug fixed during development:
- Initial design prefetched into the SAME LRU cache as demand-fetched files.
  This caused prefetched files to evict useful demand-fetched files, HURTING
  performance (-3pp at cache=16). Patterson 1995 explicitly warns about this.
  Fix: separate prefetch buffer that never evicts demand-fetched files.

Algorithm reference:
- Patterson et al. 1995, "Informed Prefetching and Caching", SOSP '95
  https://doi.org/10.1145/224056.224064
- Kroeger & Long 1996, "Predicting File-System Actions from Reference Patterns"

Stage Summary:
- Phase 3 PoC complete and validated. Markov-based prefetching improves cache hit
  rate by up to 43 percentage points on realistic game access patterns.
- CI extended to run Phase 3 PoC and validate prefetching improves hit rate >0.
- Next: Phase 4 — Shader cache infrastructure design.

---
Task ID: aurora-session-break
Agent: Main (Super Z)
Session: 2026-06-22
Task: Persist all in-chat context to GitHub before taking a break

Work Log:
- User asked to save all important context from chat to GitHub before break
- Created docs/RESEARCH_SYNTHESIS.md — the deep research findings from session 1
  (emulator landscape, why Mali fails, x86→ARM techniques, graphics translation,
  modular engines, classical algorithms, feasibility verdict)
- Created docs/COMPETITOR_COMPARISON.md — Aurora vs Winlator/Mobox/GameNative/GameHub
  (feature table, where Aurora wins/loses/ties, realistic predictions, RDR2 analysis)
- Created docs/AAA_FEASIBILITY.md — honest analysis of what we can/can't run
  (what works, what doesn't, bottleneck hierarchy, milestone path)
- Created docs/ARCHITECTURE_DECISIONS.md — 13 key decisions with rationale
  (Basis Universal, KTX2/UASTC, ASTC 4x4, meshoptimizer, Patterson prefetch,
  separate prefetch buffer, fork Box64/DXVK, Python PoC + C++ production,
  NO DRM bypass, Android 10+ target, pinned deps, CI on every push)
- Updated PROJECT_STATE.md with pointers to all docs/
- All docs committed and pushed to GitHub

Stage Summary:
- All in-chat context now persisted to GitHub at /home/z/my-project/aurora/docs/
- Next session can pick up by reading PROJECT_STATE.md → docs/ → worklog.md
- Taking a break. Phase 4 (Shader cache infrastructure) is next when we resume.
