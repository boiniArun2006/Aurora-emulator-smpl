# Aurora — Environment Variable Matrix (reference)

**Source:** GameNative's `GlibcProgramLauncherComponent.java` + `Container.java` + `DXVKHelper.java`
**Status:** Reference — these are the env vars a production Android PC emulator sets when launching a game.

Aurora's Phase 5 orchestrator will use this matrix as the default, then add Aurora-specific vars for Phases 1-4 + 6.

---

## Filesystem / runtime

| Variable | Value | Purpose |
|---|---|---|
| `HOME` | `/home/xuser` | Wine's $HOME |
| `USER` | `xuser` | Wine's $USER |
| `TMPDIR` | `/tmp` | Temp dir |
| `DISPLAY` | `:0` | X server display |
| `PATH` | `/opt/wine/bin:/usr/bin:/usr/local/bin` | Executable search path |
| `LD_LIBRARY_PATH` | `/usr/lib` | ARM64 shared libs |
| `BOX64_LD_LIBRARY_PATH` | `/usr/lib/x86_64-linux-gnu` | x86_64 libs for Box64 |
| `ANDROID_SYSVSHM_SERVER` | `/sysvshm_server` | SysV SHM socket path |
| `FONTCONFIG_PATH` | `/usr/etc/fonts` | Font config |
| `LD_PRELOAD` | `libredirect.so libandroid-sysvshm.so` | Preload ARM64 libs |
| `WINEESYNC_WINLATOR` | `1` | Wine esync variant |

---

## Box64 tuning

| Variable | Value | Purpose |
|---|---|---|
| `BOX64_NOBANNER` | `1` | Suppress startup banner |
| `BOX64_DYNAREC` | `1` | JIT compilation ON |
| `BOX64_X11GLX` | `1` | X11 GLX support |
| `BOX64_RCFILE` | `/etc/config.box64rc` | Per-game config overrides |
| `BOX64_MMAP32` | `0` | **Mali only** — workaround for Mali driver bug with 32-bit memory mappings |
| `BOX64_LOG` | `1` | Only if debug enabled |
| `BOX64_DYNAREC_MISSING` | `1` | Only if debug enabled |

---

## DXVK / graphics

| Variable | Value | Purpose |
|---|---|---|
| `DXVK_STATE_CACHE_PATH` | `/home/xuser/.cache` | **Phase 4 cache goes here** |
| `DXVK_LOG_LEVEL` | `none` | Suppress DXVK logs |
| `DXVK_CONFIG_FILE` | `/home/xuser/.config/dxvk.conf` | Per-game DXVK config |
| `DXVK_CONFIG` | (string with dxgi.* d3d11.* settings) | Inline DXVK config |
| `DXVK_GPLASYNCCACHE` | `1` | **Async pipeline library cache — key for stutter reduction** |
| `DXVK_ASYNC` | `1` | Async shader compilation |
| `DXVK_FEATURE_LEVEL` | `11_1` | Max D3D feature level |
| `DXVK_FRAME_RATE` | `60` | Frame rate cap |
| `MESA_SHADER_CACHE_DISABLE` | `false` | Mesa shader cache ON |
| `MESA_SHADER_CACHE_MAX_SIZE` | `512MB` | Mesa shader cache size |
| `MESA_VK_WSI_PRESENT_MODE` | `mailbox` | Vulkan present mode (low latency) |
| `TU_DEBUG` | `noconform` | **Turnip only** — skip conformance checks for speed |
| `VKD3D_SHADER_MODEL` | `6_0` | VKD3D shader model |
| `ZINK_DESCRIPTORS` | `lazy` | Zink (OpenGL→Vulkan) lazy descriptors |
| `ZINK_DEBUG` | `compact,deck_emu` | Zink debug flags |
| `mesa_glthread` | `true` | Mesa GL threading |
| `WINEESYNC` | `1` | Wine esync |
| `PULSE_LATENCY_MSEC` | `144` | Audio latency (high but stable) |

---

## Per-game dxvk.conf settings

| Setting | Example | Purpose |
|---|---|---|
| `dxgi.maxDeviceMemory` | `4096` | Spoof GPU memory size |
| `dxgi.maxSharedMemory` | `8192` | Spoof shared memory |
| `d3d11.maxFeatureLevel` | `11_1` | Max D3D11 feature level |
| `d3d11.constantBufferRangeCheck` | `True` | Stability workaround |
| `dxgi.customDeviceId` | `0x...` | Spoof GPU device ID |
| `dxgi.customVendorId` | `0x10de` | Spoof GPU vendor ID (NVIDIA) |
| `dxgi.customDeviceDesc` | `NVIDIA GeForce GTX 970` | Spoof GPU name |

---

## Per-game graphicsDriverConfig

| Setting | Default | Purpose |
|---|---|---|
| `vulkanVersion` | `1.3` | Min Vulkan version |
| `version` | (turnip version) | Driver version to use |
| `blacklistedExtensions` | (empty) | VK extensions to disable |
| `maxDeviceMemory` | `0` | 0 = auto-detect |
| `presentMode` | `mailbox` | Vulkan present mode |
| `syncFrame` | `0` | Frame sync |
| `disablePresentWait` | `0` | Disable VK_GOOGLE_display_timing |
| `resourceType` | `auto` | Memory resource type |
| `bcnEmulation` | `auto` | BCn texture emulation (for GPUs without native BCn) |
| `bcnEmulationType` | `compute` | How to emulate BCn |
| `bcnEmulationCache` | `0` | Cache BCn emulation results |
| `gpuName` | `Device` | Spoofed GPU name |

---

## Aurora-specific env vars (NEW — Phases 1-4 + 6)

| Variable | Value | Purpose | Phase |
|---|---|---|---|
| `AURORA_AOT_TEXTURES_PATH` | `/home/xuser/.cache/aurora_textures` | Path to KTX2/UASTC texture cache | 1 |
| `AURORA_AOT_MESHES_PATH` | `/home/xuser/.cache/aurora_meshes` | Path to LOD mesh cache | 2 |
| `AURORA_PREFETCH_MODEL` | `/home/xuser/.cache/aurora_prefetch/model.json` | Markov prefetch model path | 3 |
| `AURORA_PREFETCH_ENABLED` | `1` | Enable Markov prefetcher | 3 |
| `AURORA_SHADER_CACHE_CLOUD` | `https://cloud.aurora-emulator.org` | Cloud shader cache URL | 4 |
| `AURORA_SHADER_CACHE_SYNC` | `1` | Enable cloud shader sync | 4 |
| `AURORA_MALI_SANITIZER` | `auto` | Enable Phase 6 Mali sanitizer (auto/on/off) | 6 |
| `AURORA_LOG_LEVEL` | `info` | Aurora logging verbosity | all |

---

## Per-game Container config (Aurora additions)

These extend GameNative's `Container` class:

| Field | Default | Purpose | Phase |
|---|---|---|---|
| `auroraTextureQuality` | `default` | UASTC encode quality (fast/default/max) | 1 |
| `auroraMeshLODBias` | `0` | LOD bias (-2 = more aggressive simplification, +2 = less) | 2 |
| `auroraPrefetchEnabled` | `true` | Enable Markov prefetcher | 3 |
| `auroraPrefetchThreshold` | `0.30` | Min probability to trigger prefetch | 3 |
| `auroraShaderCloudSync` | `true` | Enable cloud shader sync | 4 |
| `auroraMaliSanitizer` | `auto` | Mali sanitizer mode | 6 |

---

## Notes

1. **`BOX64_MMAP32=0` is critical for Mali.** GameNative auto-detects Mali via `GPUInformation.getRenderer()` and sets this. Aurora's Phase 6 should do the same.

2. **`DXVK_GPLASYNCCACHE=1` is the magic flag for shader stutter.** It enables async compilation using `VK_EXT_graphics_pipeline_library`. Combined with our Phase 4 cloud shader cache, this should eliminate stutter for most games.

3. **`TU_DEBUG=noconform` is Turnip-specific.** Skips Vulkan conformance checks for ~5% performance gain. Don't set on Mali (their driver is already non-conformant in places; this flag could break things).

4. **`PULSE_LATENCY_MSEC=144` is high.** Lower values (e.g. 50ms) cause audio crackling on most devices. Old games (Unreal Gold) need even higher (90ms+).

5. **Per-game `dxgi.customDeviceId` / `customVendorId`** lets us spoof the GPU identity. Some games refuse to run on "unknown" GPUs; we spoof NVIDIA/AMD to make them happy.
