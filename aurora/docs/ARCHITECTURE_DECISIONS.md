# Aurora — Architecture Decisions Record

**Compiled:** 2026-06-22

Key decisions made during Phases 0-3, with rationale. Future sessions should read this before questioning or changing anything.

---

## Decision 1: Use Basis Universal for texture transcoding

**Status:** Accepted (Phase 1)
**Alternatives considered:**
- Custom encoder (rejected: 8+ years of work to match Basis quality)
- ETC2-only via ISPC texture codec (rejected: lower quality than UASTC, no transcoding flexibility)
- PVRTC-only (rejected: PowerVR-only, we don't target PowerVR)

**Rationale:**
- Binomial's Basis Universal is the gold standard for portable GPU texture compression
- Supports BCn↔ASTC↔ETC2↔PVRTC transcoding in microseconds per block
- Used by AAA games (Call of Duty Mobile, Genshin Impact, etc.)
- Apache 2.0 license, no royalties
- Pinned to v2_1_0r for reproducibility

---

## Decision 2: Use KTX2/UASTC as on-device storage format

**Status:** Accepted (Phase 1)
**Alternatives considered:**
- Store raw ASTC directly (rejected: no supercompression, 3-4x larger on disk)
- Store BCn and transcode at runtime (rejected: BCn→ASTC transcode is expensive, not microseconds)
- Store ETC2 (rejected: lower quality than UASTC, Mali-G610+ supports ASTC natively)

**Rationale:**
- KTX2 is the Khronos open standard container
- UASTC codec provides high quality + fast transcoding to ASTC
- Zstd supercompression on top gives 9.7x compression vs raw RGBA
- Same KTX2 file can transcode to ANY GPU format (future-proof)

---

## Decision 3: Use ASTC 4x4 as runtime GPU format

**Status:** Accepted (Phase 1)
**Alternatives considered:**
- ETC2 (rejected: lower quality, same file size)
- BCn (rejected: not supported by mobile GPUs)
- Multiple formats per device (rejected: complexity not worth it)

**Rationale:**
- Universal support on Mali-G610+ and Adreno 6xx+
- 8 bits/pixel, good quality
- Same format UASTC transcodes to natively

---

## Decision 4: Use meshoptimizer for mesh simplification

**Status:** Accepted (Phase 2)
**Alternatives considered:**
- CGAL Surface_mesh_simplification (rejected: heavy dependency, GPL license concerns)
- Custom QEM implementation (rejected: meshoptimizer's is battle-tested by AAA games)
- Blender's decimate modifier (rejected: not a library, requires Blender install)

**Rationale:**
- MIT license
- Used by Horizon Zero Dawn PC port, Call of Duty, etc.
- Extends classical QEM with attribute-aware error metric, lockable vertices
- v1.1 has 0 open bug issues
- Built as shared library for Python ctypes bindings (PoC) — will link directly in production C++

---

## Decision 5: Implement Patterson 1995 "Informed Prefetching" architecture

**Status:** Accepted (Phase 3)
**Alternatives considered:**
- LRU only (rejected: 15-37% hit rate on small caches is unacceptable)
- Sequential prefetch only (rejected: doesn't handle spatial/event patterns)
- ML-based prefetcher (rejected: too complex for PoC, Markov is sufficient)

**Rationale:**
- Patterson 1995 is the foundational OS paper on informed prefetching
- Markov models are simple, fast to train (<1ms), small (15KB)
- Validated: +43pp hit rate improvement on small caches
- Patterson explicitly warns: prefetched files MUST NOT evict demand-fetched files → we use separate prefetch buffer

---

## Decision 6: Separate prefetch buffer from main cache

**Status:** Accepted (Phase 3, bugfix)
**Alternatives considered:**
- Single shared LRU cache (rejected: caused -3pp performance regression in initial implementation)

**Rationale:**
- Patterson 1995 explicitly warns: "prefetching into the demand cache can degrade performance when the predictor is wrong"
- Initial Aurora implementation prefetched into main cache → -3pp at cache=16
- Fix: separate prefetch buffer that never evicts demand-fetched files
- Result: +37pp improvement (from -3pp regression to +37pp gain)

---

## Decision 7: Fork Box64/FEX-Emu, don't reinvent

**Status:** Accepted (architecture)
**Alternatives considered:**
- Custom x86→ARM64 translator (rejected: 10+ years of work, not a research project)
- Use QEMU TCG (rejected: too slow, ~30% of native vs Box64's 80%)

**Rationale:**
- Box64 is 10 years of ptitSeb's work, 80% of native speed
- FEX-Emu is similar performance, different design (used on Linux ARM laptops)
- Our innovation: AOT pre-translation mode (Rosetta 2 style) on top of Box64's JIT
- We extend, we don't replace

---

## Decision 8: Fork DXVK, don't reinvent

**Status:** Accepted (architecture)
**Alternatives considered:**
- Custom D3D→Vulkan layer (rejected: DXVK is excellent, 8+ years of work)
- WineD3D only (rejected: OpenGL-based, much slower than Vulkan)
- VKD3D only (rejected: D3D12 only, doesn't cover D3D9/10/11)

**Rationale:**
- DXVK is the gold standard for D3D9/10/11 → Vulkan
- VKD3D-Proton handles D3D12 → Vulkan
- Our innovation: Mali sanitizer shim (Phase 6) sits between DXVK and the Mali driver

---

## Decision 9: Python for PoC, C++ for production

**Status:** Accepted (architecture)
**Alternatives considered:**
- Pure Python (rejected: too slow for runtime emulation, can't hit 60fps)
- Pure C++ (rejected: painful for PoC iteration, 30s compile times vs 0.1s Python)
- Pure Rust (rejected: Box64/Wine/DXVK are all C++, FFI would be constant fight)

**Rationale:**
- Python PoCs validate algorithms fast (Phases 1-4)
- C++ production runtime hits latency targets (Phases 5-8)
- Kotlin for Android UI, CMake for build
- Standard emulator stack

---

## Decision 10: NO DRM bypass

**Status:** Accepted (legal/architecture)
**Alternatives considered:**
- Include Denuvo bypass (rejected: lawsuit magnet for MIT-licensed open source)
- Game-specific cracks (rejected: break constantly, unmaintainable)

**Rationale:**
- Legal: DRM circumvention is illegal in many jurisdictions (DMCA §1201, EU Copyright Directive)
- Technical: DRM bypass patches are game-specific, break on game updates
- Aurora runs any valid .exe — if users run cracked games, that's their decision
- We don't ship cracks, we don't document how to crack, we don't help with cracking

---

## Decision 11: Target Android 10+ (API 21+)

**Status:** Accepted (targeting)
**Alternatives considered:**
- Android 12+ only (rejected: excludes too many budget devices, our target market)
- Android 8+ (rejected: Vulkan 1.1 support too spotty below Android 10)

**Rationale:**
- Android 10+ has stable Vulkan 1.1
- Covers ~85% of active Android devices as of 2026
- basis_universal has a known issue (#271) with Android API <24 — documented in `third_party/patches/README.md`

---

## Decision 12: Pin all third-party dependencies to specific tags

**Status:** Accepted (Phase 1.5 audit)
**Alternatives considered:**
- Track master/main (rejected: non-reproducible, silent breakage when upstream changes)

**Rationale:**
- basis_universal: pinned to v2_1_0r (commit e4f439fc)
- meshoptimizer: pinned to v1.1 (commit dc9d09ed)
- Future deps (Box64, Wine, DXVK) will also be pinned
- MANIFEST.txt + setup_third_party.sh reproduces the build

---

## Decision 13: GitHub Actions CI on every push

**Status:** Accepted (Phase 1.5)
**Alternatives considered:**
- Manual testing only (rejected: too easy to break things silently)
- CI on release tags only (rejected: too late to catch regressions)

**Rationale:**
- Caches basis_universal + meshoptimizer builds (subsequent runs ~30s vs 2+ min)
- Runs all PoC tests (Phase 1, 2, 3)
- Validates outputs (3+ KTX2, 3+ ASTC, 4+ LODs, prefetching improves hit rate >0)
- Uploads pipeline_results.json as artifact for inspection
