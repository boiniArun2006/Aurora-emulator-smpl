# Aurora — Reference Architecture (learned from Winlator + GameNative)

**Compiled:** 2026-06-22
**Sources:**
- `reference_repos/winlator/` — brunodev85/winlator (installable components + README)
- `reference_repos/GameNative/` — utkarshdalal/GameNative (full open-source fork, 752 Kotlin files)
- Web research on Box64 env vars, DXVK state cache, Turnip driver versions

This document captures what we learned by studying real production Android
PC-game emulators, and how Aurora's Phase 5 orchestration will adapt their
patterns (NOT reinvent them).

---

## 1. The ImageFs + XEnvironment + Components pattern

**This is the canonical Android emulator architecture.** Both Winlator and
GameNative use it. Aurora will adopt it for Phase 5.

### ImageFs — the filesystem layout

A fixed directory layout inside the app's private storage that mimics a
Linux root filesystem. Wine + Box64 run inside this "chroot-like" env.

```
imagefs/                          # context.getFilesDir()/imagefs
├── .img_version                  # version tag for migration
├── .variant                      # "glibc" or "bionic"
├── opt/
│   └── wine/                     # Wine binaries (multiple versions side-by-side)
│       └── bin/wine
├── home/xuser/                   # $HOME for Wine
│   ├── .wine/                    # WINEPREFIX (registry, dosdevices, etc.)
│   ├── .cache/                   # DXVK state cache, Mesa shader cache
│   └── .config/
├── usr/
│   ├── lib/                      # ARM64 shared libs (glibc64, libredirect, sysvshm)
│   │   └── x86_64-linux-gnu/     # BOX64_LD_LIBRARY_PATH target
│   ├── bin/
│   └── local/bin/box64           # Box64 binary
├── etc/
│   ├── config.box64rc            # Box64 per-game config overrides
│   └── fonts/
└── tmp/
```

**Aurora's adaptation:** We'll use the same layout but add Aurora-specific dirs:
```
imagefs/home/xuser/.cache/
├── dxvk_state/                   # DXVK_STATE_CACHE_PATH (Phase 4)
├── aurora_textures/              # KTX2/UASTC files (Phase 1)
├── aurora_meshes/                # LOD .obj sets (Phase 2)
└── aurora_prefetch/              # Markov model + play traces (Phase 3)
```

### XEnvironment — the orchestrator

A simple container that holds a list of `EnvironmentComponent` instances
and starts/stops them in order. Critically: **components are pluggable**.
You add only the components you need for a particular game.

```java
public class XEnvironment {
    private final ArrayList<EnvironmentComponent> components = new ArrayList<>();

    public void addComponent(EnvironmentComponent c) { ... }

    public void startEnvironmentComponents() {
        for (EnvironmentComponent c : this) c.start();
    }

    public void onPause() {
        // Suspend game process FIRST, then audio components
        getComponent(GuestProgramLauncherComponent.class).suspendProcess();
        getComponent(PulseAudioComponent.class).pause();
    }

    public void onResume() {
        // Resume audio FIRST so it's ready when game wakes up
        getComponent(PulseAudioComponent.class).resume();
        getComponent(GuestProgramLauncherComponent.class).resumeProcess();
    }
}
```

**Key insight:** The onPause/onResume order matters. Audio must resume
BEFORE the game process, otherwise the game's first audio call hangs.

**Aurora's adaptation:** Our Phase 5 orchestrator will use the same
pattern but with Aurora-specific components:
- `TextureEngineComponent` (Phase 1 — wraps Basis transcoder)
- `MeshEngineComponent` (Phase 2 — wraps meshoptimizer)
- `LoaderEngineComponent` (Phase 3 — wraps Markov prefetcher)
- `ShaderEngineComponent` (Phase 4 — wraps cloud shader cache)
- `MaliSanitizerComponent` (Phase 6 — the novel part)
- `Box64Component`, `WineComponent`, `DXVKComponent` (Phase 7)

---

## 2. Component list (what GameNative ships)

From `xenvironment/components/`:

| Component | Purpose | Aurora equivalent |
|---|---|---|
| `ALSAServerComponent` | Audio (ALSA → Android audio) | `AudioEngineComponent` |
| `PulseAudioComponent` | Audio (PulseAudio server in userspace) | same |
| `BionicProgramLauncherComponent` | Launch game via Android's bionic libc | n/a (we use glibc path) |
| `GlibcProgramLauncherComponent` | Launch game via bundled glibc | `Box64LauncherComponent` |
| `GuestProgramLauncherComponent` | Base class for launchers | base class |
| `NetworkInfoUpdateComponent` | Inject network info into Wine | same |
| `SteamClientComponent` | Steam integration | future |
| `SysVSharedMemoryComponent` | SysV SHM emulation (Android lacks it) | same |
| `VirGLRendererComponent` | VirGL (OpenGL over network) fallback | n/a (we use Turnip) |
| `VortekRendererComponent` | Vortek (proprietary DX9-11 wrapper) | n/a |
| `WineRequestComponent` | Handle Wine's requests to Android | same |
| `XServerComponent` | Embedded X server for Wine's GUI | same |

**Aurora's addition:** None of these competitors have:
- Texture/mesh/loader/shader engine components (our Phases 1-4)
- Mali sanitizer component (our Phase 6)
- AOT preprocessing pipeline (our Phases 1-4)

---

## 3. Environment variable matrix (the actual orchestration)

This is the **most important** finding. Here's every env var GameNative
sets when launching a game, grouped by purpose:

### Filesystem / runtime env
```
HOME=/home/xuser
USER=xuser
TMPDIR=/tmp
DISPLAY=:0
PATH=/opt/wine/bin:/usr/bin:/usr/local/bin
LD_LIBRARY_PATH=/usr/lib
BOX64_LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu
ANDROID_SYSVSHM_SERVER=/sysvshm_server
FONTCONFIG_PATH=/usr/etc/fonts
LD_PRELOAD=libredirect.so libandroid-sysvshm.so
```

### Box64 tuning
```
BOX64_NOBANNER=1
BOX64_DYNAREC=1                    # JIT compilation on
BOX64_X11GLX=1                     # X11 GLX support
BOX64_RCFILE=/etc/config.box64rc   # per-game config file
BOX64_MMAP32=0                     # OFF on Mali (works around Mali driver bug)
BOX64_LOG=1                        # only if debug enabled
BOX64_DYNAREC_MISSING=1            # only if debug enabled
```

**CRITICAL FINDING:** `BOX64_MMAP32=0` is set ONLY when GPU is Mali.
This is a workaround for a Mali driver bug with 32-bit memory mappings.
Aurora's Phase 6 (Mali sanitizer) should automate this kind of workaround.

### DXVK / graphics
```
DXVK_STATE_CACHE_PATH=/home/xuser/.cache    # Phase 4 cache goes here
DXVK_LOG_LEVEL=none
DXVK_CONFIG_FILE=/home/xuser/.config/dxvk.conf
DXVK_CONFIG="dxgi.maxDeviceMemory=4096 d3d11.maxFeatureLevel=11_1 ..."
DXVK_GPLASYNCCACHE=1               # async pipeline library cache (key for stutter reduction)
DXVK_ASYNC=1                       # async shader compilation
DXVK_FEATURE_LEVEL=11_1
DXVK_FRAME_RATE=60
MESA_SHADER_CACHE_DISABLE=false
MESA_SHADER_CACHE_MAX_SIZE=512MB
MESA_VK_WSI_PRESENT_MODE=mailbox
TU_DEBUG=noconform                 # Turnip: skip conformance checks for speed
VKD3D_SHADER_MODEL=6_0
ZINK_DESCRIPTORS=lazy              # Zink (OpenGL->Vulkan): lazy descriptors
ZINK_DEBUG=compact,deck_emu
mesa_glthread=true
WINEESYNC=1
PULSE_LATENCY_MSEC=144
```

### Per-game config (in dxvk.conf)
```
dxgi.maxDeviceMemory = 4096
dxgi.maxSharedMemory = 8192
d3d11.maxFeatureLevel = 11_1
d3d11.constantBufferRangeCheck = True    # stability workaround
dxgi.customDeviceId = ...                # spoof GPU identity
dxgi.customVendorId = ...
```

**Aurora's adaptation:** Our Phase 5 will use this exact env var matrix
as the default, then add Aurora-specific ones:
```
AURORA_AOT_TEXTURES_PATH=/home/xuser/.cache/aurora_textures
AURORA_AOT_MESHES_PATH=/home/xuser/.cache/aurora_meshes
AURORA_PREFETCH_MODEL=/home/xuser/.cache/aurora_prefetch/model.json
AURORA_SHADER_CACHE_CLOUD=https://cloud.aurora-emulator.org
AURORA_MALI_SANITIZER=1               # enable Phase 6 sanitizer
```

---

## 4. Installable components strategy (Winlator)

Winlator ships pre-built `.tzst` (zstd-compressed tar) archives for each
major component, with an `index.txt` manifest. At runtime, the user
picks which version to extract.

```
installable_components/
├── box64/
│   ├── index.txt
│   ├── box64-0.3.3.tzst
│   ├── box64-0.3.5.tzst
│   └── box64-0.3.7.tzst
├── dxvk/
│   ├── index.txt
│   ├── dxvk-0.96.tzst ... dxvk-2.6.1.tzst
├── turnip/
│   ├── index.txt
│   └── turnip-24.1.0.tzst ... turnip-26.0.3.tzst
├── vkd3d/
├── wined3d/
```

GameNative extends this with a `manifest.json` that includes download URLs
so users can fetch newer versions without an app update:

```json
{
  "driver": [
    {"id": "turnip26.0.0_R8", "url": "https://downloads.gamenative.app/drivers/turnip26.0.0_R8.zip"},
    ...
  ]
}
```

**Aurora's adaptation:** Same strategy, but with **pinned versions** in
`third_party/MANIFEST.txt` (which we already have). We'll add:
- `box64`, `wine`, `dxvk`, `vkd3d`, `turnip`, `panvk` to the manifest
- A component downloader that fetches by URL (like GameNative)
- Signature verification (signatures in manifest, public key in app)
- **NEW:** Aurora-specific components (texture/mesh/shader engines) bundled
  as versioned `.tzst` archives, downloaded on first launch

---

## 5. Per-game config (the Container pattern)

GameNative's `Container` class is the per-game config object. Each game
gets its own container with:

- `screenSize` (e.g. "1280x720")
- `envVars` (override the defaults)
- `graphicsDriver` (turnip / virgl / vortek)
- `dxwrapper` (dxvk / wined3d / none)
- `dxwrapperConfig` (version + per-game DXVK settings)
- `graphicsDriverConfig` (vulkan version, present mode, BCn emulation, etc.)
- `wincomponents` (which Wine DLL overrides to enable)
- `box64Preset` (compatibility / performance / stability)
- `drives` (D:, E:, etc. mappings to Android storage)
- `startupSelection` (normal / essential / aggressive — process priority)
- `suspendPolicy` (auto / never / manual — when to pause game)

**Defaults are excellent** — here's GameNative's `DEFAULT_ENV_VARS`:
```
WRAPPER_MAX_IMAGE_COUNT=0
ZINK_DESCRIPTORS=lazy
ZINK_DEBUG=compact,deck_emu
MESA_SHADER_CACHE_DISABLE=false
MESA_SHADER_CACHE_MAX_SIZE=512MB
mesa_glthread=true
WINEESYNC=1
MESA_VK_WSI_PRESENT_MODE=mailbox
TU_DEBUG=noconform
VKD3D_SHADER_MODEL=6_0
PULSE_LATENCY_MSEC=144
```

And `DEFAULT_GRAPHICSDRIVERCONFIG`:
```
vulkanVersion=1.3
blacklistedExtensions=
maxDeviceMemory=0
presentMode=mailbox
syncFrame=0
disablePresentWait=0
resourceType=auto
bcnEmulation=auto
bcnEmulationType=compute
bcnEmulationCache=0
gpuName=Device
```

**Aurora's adaptation:** We'll copy this exact default set (it's been
tuned by thousands of GameNative users) and add Aurora-specific fields:
- `auroraTextureQuality` (fast / default / max — Phase 1)
- `auroraMeshLODBias` (-2 to +2 — Phase 2)
- `auroraPrefetchEnabled` (true / false — Phase 3)
- `auroraShaderCloudSync` (true / false — Phase 4)
- `auroraMaliSanitizer` (auto / on / off — Phase 6)

---

## 6. Input controls per-game (the .icp pattern)

Winlator ships 53 pre-made `.icp` (Input Control Profile) files for
specific games: Skyrim, GTA 5, Fallout 3, Bioshock, Mass Effect 2, etc.

GameNative extends this with `steaminput/` assets that map to Steam Input
controller mappings (so Steam games auto-detect the right layout).

**Aurora's adaptation:** Same pattern. We'll ship:
- `assets/inputcontrols/*.icp` (Winlator-format for compatibility)
- A community-updatable input control repository (download new profiles)
- Auto-detect game → suggest best input profile

---

## 7. Audio architecture

GameNative uses two audio paths:
1. **ALSA server** (in-userspace, via `ALSAServerComponent`) — for old games
2. **PulseAudio server** (in-userspace, via `PulseAudioComponent`) — for modern games

Both translate Wine's audio calls to Android's `AAudio` / `OpenSL ES`.

Default latency: `PULSE_LATENCY_MSEC=144` (high but stable; lower values
cause crackling on most devices).

**Aurora's adaptation:** Same architecture. Audio is solved — don't reinvent.
The only Aurora addition: integrate with the Phase 3 prefetcher to preload
audio chunks during level transitions.

---

## 8. GPU driver loading (Turnip hot-swap)

This is the magic that makes Adreno work well. `nihui/mesa-turnip-android-driver`
showed the world that you can hot-swap Turnip at runtime by setting:

```
LD_LIBRARY_PATH=/path/to/turnip/libvulkan.so
```

...before launching the game. The system Vulkan loader picks up the Turnip
library instead of the Qualcomm blob.

GameNative's `manifest.json` lists ~10 Turnip versions because different
versions have different performance characteristics on different Adreno gens:
- turnip 24.x — Adreno 6xx
- turnip 25.x — Adreno 7xx (early)
- turnip 26.x — Adreno 7xx (late) + 8xx

**Aurora's adaptation:** Same hot-swap mechanism for Adreno. For Mali,
we can't hot-swap (kernel driver mismatch — see RESEARCH_SYNTHESIS.md §2b),
so Phase 6 (Mali sanitizer) is our path instead.

---

## 9. What Aurora will do DIFFERENTLY (the novel parts)

These are the pieces NO competitor has. This is Aurora's value prop.

### Phase 1-4: AOT preprocessing pipeline
- **Texture Engine**: BCn → KTX2/UASTC → ASTC (3.2-4.2x compression validated)
- **Mesh Engine**: QEM simplification at 4 LOD levels (validated)
- **Loader Engine**: Markov prefetcher (+43pp hit rate validated)
- **Shader Engine**: Community cloud shader cache (100% hit rate for 2nd user validated)

No competitor does any of these. GameNative uses DXVK's built-in state
cache but doesn't sync to cloud. Winlator ships nothing.

### Phase 6: Mali Vulkan sanitizer
A Vulkan layer (loaded via `VK_INSTANCE_LAYERS`) that sits between DXVK
and the Mali driver. Detects unsupported extensions, rewrites buggy call
patterns, emulates missing features in software.

No competitor has anything like this. This is the only path to making
Mali viable without kernel source.

### Phase 5: Orchestration that ties it all together
The XEnvironment + Components pattern (from GameNative) is our base.
We add Aurora-specific components that:
- Run AOT preprocessing on game install (Phases 1-4)
- Set up env vars for the runtime engines (Phases 1-4)
- Load the Mali sanitizer if GPU is Mali (Phase 6)
- Coordinate pause/resume across all engines

---

## 10. What Aurora will NOT do differently

These are solved problems. Use the existing patterns.

- **CPU translation**: Box64 (fork, don't reinvent)
- **Win32 API**: Wine (use upstream)
- **D3D→Vulkan**: DXVK (fork, add Mali sanitizer)
- **Audio**: ALSA + PulseAudio components (copy from GameNative)
- **X server**: embedded X server (copy from GameNative)
- **Input controls**: .icp format (Winlator-compatible)
- **Installable components**: .tzst archives + index.txt + manifest.json
- **GPU driver loading**: LD_LIBRARY_PATH hot-swap (for Adreno)
- **Filesystem layout**: imagefs/ pattern
- **Per-game config**: Container pattern with sensible defaults

---

## 11. Concrete Phase 5 plan (informed by this research)

Based on the above, Phase 5 will:

1. **Create `src/orchestrator/` with:**
   - `aurora_environment.py` — Python PoC of XEnvironment (mirrors GameNative's Java)
   - `aurora_imagefs.py` — sets up imagefs/ layout
   - `aurora_container.py` — per-game config (Container pattern)
   - `aurora_env_vars.py` — env var matrix (defaults from GameNative + Aurora additions)
   - `components/` — pluggable components, one per engine + base class

2. **Components to implement (Python PoC):**
   - `TextureEngineComponent` — wraps Phase 1, sets AURORA_AOT_TEXTURES_PATH
   - `MeshEngineComponent` — wraps Phase 2, sets AURORA_AOT_MESHES_PATH
   - `LoaderEngineComponent` — wraps Phase 3, sets AURORA_PREFETCH_MODEL
   - `ShaderEngineComponent` — wraps Phase 4, populates DXVK_STATE_CACHE_PATH
   - `Box64Component` (stub for now — full impl in Phase 7)
   - `WineComponent` (stub for now — full impl in Phase 7)
   - `DXVKComponent` (stub for now — full impl in Phase 7)

3. **PoC test:**
   - Simulate game install: run all 4 AOT engines, populate cache dirs
   - Simulate game launch: build env var matrix, "launch" with stub components
   - Verify all env vars set correctly, all cache dirs populated
   - Validate pause/resume ordering (audio before game)

4. **For production (Phase 8):**
   - Port to Kotlin + JNI (same architecture, native performance)
   - Bundle as Android APK

---

## 12. Key takeaways

1. **Don't reinvent the orchestration pattern.** ImageFs + XEnvironment + Components is proven by 2 production emulators. Use it.

2. **The env var matrix is the secret sauce.** GameNative's defaults are the result of thousands of hours of community testing. Start from their defaults, add Aurora-specific vars.

3. **Per-game config (Container) is essential.** Different games need different settings. GameNative's `dxwrapperConfig` string format is elegant — copy it.

4. **Installable components strategy (.tzst + manifest) is the right way to ship Box64/Wine/DXVK versions.** Lets us update without app updates.

5. **Audio is solved.** ALSA + PulseAudio in userspace. Just copy GameNative's components.

6. **Our differentiation is in the engines + Mali sanitizer.** Phases 1-4 + Phase 6. Phase 5 orchestration should be a thin layer that uses the proven patterns and just wires our engines in.
