# Aurora Integration Plan — Phase by Phase into GameNative

**Started:** 2026-06-22
**Base:** GameNative latest commit (b8876a2b)
**Goal:** Integrate Aurora's Phase 1-6 engines into GameNative's real Android app

---

## Integration Points (from studying GameNative source)

### 1. Game Launch Flow
```
XServerScreen.kt:setupXEnvironment() (line 3062)
  → Creates XEnvironment
  → Adds components: SysVSharedMemory, XServer, Audio, GlibcProgramLauncher
  → XEnvironment.startEnvironmentComponents()
    → GlibcProgramLauncherComponent.execGuestProgram() (line 172)
      → Sets all env vars (HOME, BOX64_*, DXVK_*, MESA_*, etc.)
      → execve("box64", "wine", game.exe, envVars)
```

### 2. Container Creation Flow
```
ContainerUtils.kt:createNewContainer() (line 641)
  → Creates Container with per-game config
  → Sets up Wine prefix (drive_c, system32, etc.)
  → Installs DXVK DLLs
  → Game files placed in drive_c
```

### 3. Per-Game Config
```
Container.java
  → envVars (string, KEY=VAL pairs)
  → graphicsDriver, dxwrapper, dxwrapperConfig
  → screenSize, audioDriver, box64Preset
```

---

## Phase Integration Order

### Phase 6: Mali Vulkan Sanitizer (FIRST — defining feature)
**Integration point:** `GlibcProgramLauncherComponent.execGuestProgram()` (line 172)
**What to do:**
1. Create `libaurora_mali_sanitizer.so` — a C++ Vulkan layer
   - Implements `vkGetInstanceProcAddr` / `vkGetDeviceProcAddr`
   - Intercepts `vkCreateDevice` to filter blacklisted extensions
   - Intercepts `vkCmdBindDescriptorSets` to split >4 sets
   - Intercepts `vkAllocateDescriptorSets` to chunk large allocations
2. Bundle .so in `app/src/main/jniLibs/arm64-v8a/`
3. In `execGuestProgram()`, when GPU is Mali:
   ```java
   if (GPUInformation.getRenderer(context).contains("Mali")) {
       envVars.put("VK_INSTANCE_LAYERS", "libaurora_mali_sanitizer.so");
       envVars.put("VK_LAYER_PATH", imageFs.getRootDir() + "/usr/lib");
   }
   ```

### Phase 4: Cloud Shader Cache (SECOND — high impact, no C++ needed)
**Integration point:** `XServerScreen.kt:setupXEnvironment()` (before startEnvironmentComponents)
**What to do:**
1. Create `ShaderCacheSync.kt` — downloads cloud shader cache before launch
2. In `setupXEnvironment()`, before starting components:
   ```kotlin
   ShaderCacheSync.downloadIfAvailable(context, container, gpuInfo)
   ```
3. Downloads pre-compiled PSO cache to `DXVK_STATE_CACHE_PATH`

### Phase 7a: Auto-Installer (THIRD — user-visible, no C++ needed)
**Integration point:** `ContainerUtils.kt:createNewContainer()` (line 641)
**What to do:**
1. Port `PreInstallStep` interface from Python to Kotlin
2. Port VcRedistStep, DirectXStep, PhysXStep
3. Port ExeDetector (PE parser + 5-tier heuristic)
4. During container creation, after game files are placed:
   ```kotlin
   val autoInstaller = AutoInstaller()
   val result = autoInstaller.analyze(gameDir)
   WineHelper.runInstallCommands(result.toWineBatchCommand())
   ```

### Phase 1: AOT Texture Transcoder (FOURTH)
**Integration point:** `ContainerUtils.kt:createNewContainer()` (after auto-installer)
**What to do:**
1. Build Basis Universal as a C++ library for Android (already have CMake)
2. Create `TextureEngineComponent` that runs during container creation
3. Scans game directory for .dds textures
4. Transcodes to KTX2/UASTC → ASTC
5. Stores in `imagefs/home/xuser/.cache/aurora_textures/`

### Phase 2: Mesh Simplification (FIFTH)
**Integration point:** Same as Phase 1
**What to do:**
1. Build meshoptimizer as a C++ library for Android (already have CMake)
2. Create `MeshEngineComponent` that runs during container creation
3. Scans for .obj/.glb meshes
4. Simplifies at 4 LOD levels via QEM
5. Stores LODs in `imagefs/home/xuser/.cache/aurora_meshes/`

### Phase 3: Markov Prefetcher (SIXTH)
**Integration point:** `GlibcProgramLauncherComponent.execGuestProgram()` (env vars)
**What to do:**
1. Port MarkovPrefetcher from Python to Kotlin
2. Create `LoaderEngineComponent` that loads the model at game start
3. Set `AURORA_PREFETCH_MODEL` env var
4. Use `posix_fadvise(POSIX_FADV_WILLNEED)` via JNI for actual prefetching
