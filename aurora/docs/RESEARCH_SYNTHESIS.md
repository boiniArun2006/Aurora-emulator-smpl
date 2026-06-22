# Aurora Emulator — Research Synthesis

**Compiled:** 2026-06-22
**Sources:** 20 parallel web searches across GitHub, Reddit, ARM dev forums, Mesa trackers, academic papers, Khronos conformance lists, emulator dev blogs.

This document captures the research that informed Aurora's architecture. It's the "why" behind every design decision.

---

## 1. Current Android PC-Emulator Landscape

### The dominant stack
```
x86 game binary
   ↓
Box64 / Box86     (x86-64 → ARM64 translator, by ptitSeb)
   ↓
Wine              (Win32 API → Linux translation)
   ↓
DXVK / VKD3D      (DirectX 9/10/11/12 → Vulkan)
   ↓
Turnip / VirGL    (Vulkan driver for Adreno; VirGL is OpenGL fallback)
   ↓
Android GPU driver (Adreno > Mali >>> PowerVR)
```

### The big 3 projects

| Project | Architecture | Strengths | Weakness |
|---|---|---|---|
| **Winlator** (brunodev85 / winebox64 fork) | PRoot → Linux env → Wine + Box64 + Mesa (Turnip/Zink/VirGL) | Most polished GUI, no root, supports Adreno well | Mali support basically broken |
| **Mobox** (olegos2) | Termux-based → Box64 + Wine + Turnip | Lighter, more flexible, community-driven | Same Mali problem; setup harder |
| **GameHub / Cassia / ExaGear (defunct)** | Commercial attempts | Polished UX | Mostly abandoned or limited |

---

## 2. Why Mali specifically fails

Ranked by impact:

### (a) ARM's proprietary Mali Vulkan driver is buggy & feature-incomplete
- Missing or broken support for **VK_EXT_descriptor_indexing** (bindless textures) — DXVK leans heavily on this for D3D11-style constant buffer / SRV arrays
- Poor **VK_KHR_shader_subgroup** coverage — DXVK's compute shaders use subgroups for fast clear/blit ops
- Pipeline cache is notoriously unreliable → **massive shader stutter** on first encounters
- MSAA on Mali-G52/G72 has 100% crash rate in some titles (confirmed by Unreal Engine forum)

### (b) No open-source alternative that works on stock Android kernels
- **Turnip** (Mesa's Adreno Vulkan driver) works on Android because Qualcomm's kernel driver is permissive — community Mesa can drive the hardware directly
- **Panfrost / Panthor / PanVK** (Mesa's Mali drivers) exist and are getting good — but require the **Panfrost kernel driver**, which most Android devices don't ship. ARM's `kbase`/`csf` kernel driver is incompatible.
- So even though PanVK has Vulkan 1.3 conformance, you can't drop it into a stock Mali phone like you can drop Turnip into a stock Adreno phone. **This is the single biggest blocker.**

### (c) Memory architecture & driver overhead
- Adreno uses a unified memory model with efficient CPU↔GPU sharing — DXVK's staging buffers map naturally
- Mali has stricter memory domains and tile-based deferred rendering (TBDR) — DXVK was designed assuming immediate-mode rendering (PC GPUs). Some DXVK patterns cause unnecessary tile resolves on Mali.

### Bottom line on Mali
- **Older Mali (G51, G52, G72, G76)** → essentially hopeless without kernel source
- **Valhall (G57, G77, G78, G610)** → hardware is capable but stock driver quality kills it
- **Immortalis-G720 / Mali-G920** → modern, ARM's drivers are better here; might work with compromises

---

## 3. x86 → ARM64 translation: what works, what's underused

Box64 hits ~80% of native speed on OpenArena benchmarks. FEX-Emu is similar. Apple Rosetta 2 is the gold standard (~70-90% native, sometimes near parity).

### Key techniques currently used:
- **Hybrid JIT + interpreter**: Box64 translates hot blocks at runtime, falls back to interpreter for cold/rare instructions
- **Lazy flags**: x86's RFLAGS computed only when read, not on every ALU op (huge win)
- **Block chaining**: jump-to-jump optimization, avoiding dispatcher round-trips
- **Library wrapping**: Win32/Linux libraries that have native ARM equivalents get **forwarded directly** instead of translated

### Underused / could be novel:

#### AOT pre-translation (the Rosetta 2 trick)
Rosetta 2's secret sauce is **ahead-of-time translation**: when you launch an x86 app the first time, Rosetta translates the entire text segment to ARM64 and caches the result. Subsequent launches are near-native.

**This is the biggest opportunity for a new Android emulator.** On game install, scan the `.exe` and `.dll` files, AOT-translate all hot paths using profile data from a community database. Cache the ARM64 binaries in the game's data directory.

There's a 2025 paper called **"Elevator"** (arxiv 2605.08419) that does fully-static whole-binary x86-64 → AArch64 translation without heuristics.

#### The TSO problem
x86 is **TSO** (Total Store Order); ARM is **weakly ordered**. Emulators like QEMU insert a memory fence after every store → kills performance. Apple M1 has a **hardware TSO toggle** for exactly this reason.

ARM64 has the **LDAPR/StLR** instructions (acquire-release semantics) which can give TSO-equivalent behavior cheaply on ARMv8.3+. Box64 uses these.

#### Profile-guided pre-translation
- DynamoRIO / Pin / Valgrind all do hot-trace detection at runtime
- For a game emulator: run the game for 5 minutes under a tracer, identify top-N hot traces, AOT-compile them with heavy optimization, cache as a per-game "translation profile"

---

## 4. Graphics translation: where the bottleneck really is

### DXVK's main pain points
1. **Shader compilation stutter** — DXVK translates D3D shaders to SPIR-V on first encounter. On Adreno+Turnip, the Vulkan driver compiles SPIR-V → GPU bytecode fast. On Mali, the driver's compiler is slow & single-threaded → **massive stutter**
2. **Bindless resources** — D3D11 games increasingly use bindless textures. Requires `VK_EXT_descriptor_indexing`. Mali drivers are buggy here.
3. **Pipeline state objects (PSOs)** — Each unique (shader + render state) combo = one PSO = one Vulkan pipeline. Modern DXVK uses **VK_EXT_graphics_pipeline_library** to pre-compile shader "lego pieces" and fast-link them at runtime. Mali support is spotty.

### The single biggest unlock: AOT shader pre-caching
Steam Deck does this. So does NVIDIA's recent beta driver:
- Crowdsourced: users play the game → upload the shader permutation hashes they encountered → Steam pushes them to other users
- On first launch, Steam pre-compiles all known shader permutations in the background
- Result: zero stutter during gameplay

**For an Android emulator**, this could be even better:
- Build a community cloud service where users upload encountered PSO hashes + D3D bytecode
- On game install, download the pre-built Vulkan pipeline cache for the user's GPU
- **Especially valuable for Mali** because on-device compile is so slow

### Custom Vulkan shim layer for Mali
A thin "Vulkan sanitizer" layer between DXVK and the Mali driver:
- Detects unsupported extensions → falls back to a slower path that doesn't use them
- Detects known buggy call patterns → rewrites them
- Implements missing features in software (subgroup ops → emulated with shared memory)
- Reports Mali-specific quirks back to DXVK so it can adjust

**Not currently done by anyone.** This is Aurora's Phase 6.

### Fallback to OpenGL ES via Zink
For ancient Mali devices where Vulkan is broken, falling back to GLES 3.2 via WineD3D could be a "low quality but it works" mode.

---

## 5. Modular engines idea — validated by precedent

| Engine | Responsibility | Existing tech to borrow from |
|---|---|---|
| **Loader Engine** | Predictive file prefetching | Patterson's *Informed Prefetching* (1995); Markov prefetch models |
| **Texture Engine** | BCn→ASTC transcoding | Basis Universal / KTX2 |
| **Mesh Engine** | AOT mesh simplification | Garland & Heckbert's *QEM* (1997); Hoppe's *Progressive Meshes* (1996) |
| **World Engine** | Chunked streaming | GTA-style chunk streaming; VT; clipmaps |
| **Shader Engine** | Pre-compile PSOs | Steam Deck shader cache; DXVK's graphics pipeline library |
| **Audio Engine** | WASAPI → AAudio | AAudio low-latency path; Oboe |
| **CPU Translator** | x86 → ARM64 | Box64 / FEX-Emu / Rosetta 2 |
| **Graphics Translator** | D3D → Vulkan | DXVK + VKD3D + custom sanitizer |
| **Scheduler** | Coordinates engines | EnkiTS, Intel TBB |

### Precedent
- **RetroArch / libretro** — exactly this pattern for console emulators. Successful for 10+ years.
- **PPSSPP** — Henrik Rydgård deliberately kept it modular; one of the most successful mobile emulators
- **Dolphin** — clearly separated CPU/JIT core, video backend, audio DSP, HLE/LLE modules

---

## 6. Classical algorithms & math that help

### Texture transcoding
- **Basis Universal** (Binomial, ~2019): supercompressed intermediate format
- **ASTC** (Nystad et al., SIGGRAPH 2012): modern mobile texture format
- **QuickETC2** (Nah & Kim, 2020): fast ETC2 encoder

### Mesh simplification
- **Quadric Error Metrics** (Garland & Heckbert, 1997): the gold standard
- **Progressive Meshes** (Hoppe, 1996): streams LOD levels at runtime
- **Out-of-core simplification** (Lindstrom, 2000): for huge meshes

### Predictive prefetching
- **Informed Prefetching and Caching** (Patterson et al., 1995)
- **Markov prefetch** (Kroeger & Long, 1996)
- **Play-trace sharing**: Multiple users' traces → aggregated prefetch model

### Frame upscaling
- **AMD FSR 1/2/3** — fully open source, runs on any Vulkan GPU
- **Integer scaling** for pixel art games

### Binary translation theory
- **Dynamo** (Bala et al., 2000): foundational paper
- **HP DynamoRIO / Pin**: production-grade DBI frameworks
- **Elevator** (2025): fully-static whole-binary x86-64 → AArch64 translator

---

## 7. The honest feasibility verdict

| Component | Difficulty | Status |
|---|---|---|
| x86 → ARM64 translator | 🟢 Medium | Box64/FEX-Emu already do this well |
| Wine | 🟢 Solved | Just use Wine |
| D3D → Vulkan translation | 🟡 Medium | DXVK works great; tuning for Mali is the work |
| **Mali Vulkan driver problem** | 🔴 Hard | This is the fundamental blocker |
| Modular asset engines | 🟢 Medium | Novel for emulation, techniques proven |
| AOT asset preprocessing | 🟢 Easy-ish | Basis transcoders, mesh simplifiers exist |
| AOT shader pre-caching | 🟡 Medium | Doable; needs community infrastructure |
| FSR / upscaling | 🟢 Easy | Drop in FSR 1 |
| Predictive prefetch | 🟡 Medium | Engineering work, not research |

### What we should NOT try to invent
- A new CPU translator from scratch. Box64/FEX-Emu are 10 years of work — fork them.
- A new D3D→Vulkan layer. DXVK is excellent — extend it.
- A new Wine. Don't.

**Real innovation opportunity:** orchestration layer + AOT preprocessing + Mali sanitizer. That's where existing emulators are weak.
