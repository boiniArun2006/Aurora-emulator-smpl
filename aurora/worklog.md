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
