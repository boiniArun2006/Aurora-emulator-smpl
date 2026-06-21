# Aurora — Hybrid PC-Game Emulator for Android

A modular, AOT-preprocessing emulator architecture targeting mid/low-end Android devices, including Mali GPU devices that current emulators (Winlator, Mobox) fail on.

## Quick Start

```bash
# Run Phase 1 PoC (AOT Texture Transcoder)
cd /home/z/my-project/aurora
python3 src/texture_engine/aot_texture_transcoder.py test --quality fast
```

## Status

- ✅ Phase 1: AOT Texture Transcoder (Basis Universal)
- ⏳ Phase 2: Mesh Simplification Engine (Garland-QEM)
- ⏳ Phase 3+: Loader, Shader, Orchestration, Mali sanitizer, Integration, APK

See `PROJECT_STATE.md` for full status and `worklog.md` for chronological log.

## Architecture

```
PC game (x86 + D3D + BCn textures)
        ↓  [AOT preprocessing on install]
    Aurora Preprocessor:
      - Texture Engine: BCn → KTX2/UASTC (supercompressed)
      - Mesh Engine:    Simplify meshes via QEM at multiple LODs
      - Shader Engine:  Pre-compile D3D shader bytecode → SPIR-V
      - Loader Engine:  Build predictive prefetch profile
        ↓
    Mobile-optimized game bundle
        ↓  [Runtime on Android]
    Aurora Runtime:
      - Box64 (fork):          x86-64 → ARM64 translation (with AOT mode)
      - Wine:                   Win32 API translation
      - DXVK (fork):            D3D → Vulkan (with Mali sanitizer shim)
      - Turnip / PanVK:         Vulkan driver for Adreno / Mali
      - Basis Transcoder:       KTX2/UASTC → ASTC (library call, microseconds)
      - FSR 1/2/3:              Frame upscaling (free fps boost)
```

## License

- Aurora code: TBD (likely MIT or Apache 2.0)
- Third-party:
  - Basis Universal: Apache 2.0 (Binomial LLC)
  - Box64: MIT
  - Wine: LGPL-2.1
  - DXVK: zlib/libpng
  - FEX-Emu: MIT
