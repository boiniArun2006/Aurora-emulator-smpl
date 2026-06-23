#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5 PoC: Orchestration Layer
====================================================

Simulates the full game install + game launch flow using the AuroraEnvironment
orchestrator. Exercises all 4 AOT engines (Phases 1-4) + stubs for Phase 7
components (Box64, Audio).

Validates:
- ImageFs layout is created correctly
- All 4 AOT engines run on install (preprocess_on_install)
- Env var matrix is built correctly (including Mali/Adreno-specific vars)
- Pause/resume ordering is correct (audio first on resume, launcher first on pause)
- Component lifecycle (start/stop) works
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add src/ to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from orchestrator.aurora_imagefs import ImageFs
from orchestrator.aurora_container import Container
from orchestrator.aurora_gpu import GPUInfo
from orchestrator.aurora_environment import AuroraEnvironment
from orchestrator.aurora_env_vars import EnvVars
from orchestrator.components.texture_engine import TextureEngineComponent
from orchestrator.components.mesh_engine import MeshEngineComponent
from orchestrator.components.loader_engine import LoaderEngineComponent
from orchestrator.components.shader_engine import ShaderEngineComponent
from orchestrator.components.mali_sanitizer import MaliSanitizerComponent
from orchestrator.components.box64_launcher import Box64LauncherComponent
from orchestrator.components.audio import AudioComponent


def run_poc(output_dir: Path, gpu_type: str = "mali"):
    """Run the Phase 5 PoC.

    Args:
        output_dir: Where to create the imagefs/ directory
        gpu_type: "adreno" or "mali" or "immortalis" - which GPU to simulate
    """
    print("=== Aurora Emulator - Phase 5 PoC: Orchestration Layer ===\n")

    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Pick GPU ----
    if gpu_type == "adreno":
        gpu_info = GPUInfo.simulate_adreno()
    elif gpu_type == "mali":
        gpu_info = GPUInfo.simulate_mali()
    elif gpu_type == "immortalis":
        gpu_info = GPUInfo.simulate_immortalis()
    else:
        raise ValueError(f"Unknown gpu_type: {gpu_type!r}")

    print(f"[Config] GPU: {gpu_info.renderer} ({gpu_info.vendor})")
    print(f"[Config] Driver: {gpu_info.driver_version}")
    print(f"[Config] is_mali: {gpu_info.is_mali} (triggers BOX64_MMAP32=0)")
    print(f"[Config] is_adreno: {gpu_info.is_adreno} (triggers TU_DEBUG=noconform)")
    print()

    # ---- Create ImageFs ----
    print("[1/6] Creating ImageFs (Linux-like filesystem layout) ...")
    image_fs_root = output_dir / "imagefs"
    image_fs = ImageFs.create(image_fs_root)
    summary = image_fs.summary()
    print(f"      Root: {summary['root_dir']}")
    print(f"      Version: {summary['version']}, Variant: {summary['variant']}")
    print(f"      Aurora cache paths:")
    for k, v in summary["aurora_paths"].items():
        print(f"        {k}: {v}")
    print()

    # ---- Create Container (per-game config) ----
    print("[2/6] Creating Container (per-game config) ...")
    container = Container.create(
        container_id="witcher3_1.32",
        name="The Witcher 3: Wild Hunt",
    )
    csum = container.summary()
    print(f"      ID: {csum['id']}")
    print(f"      Name: {csum['name']}")
    print(f"      Screen: {csum['screenSize']}")
    print(f"      Graphics driver: {csum['graphicsDriver']}")
    print(f"      DXVK: {csum['dxwrapper']}")
    print(f"      Box64: {csum['box64Version']}")
    print(f"      Aurora config: {csum['aurora']}")
    print()

    # ---- Create Environment ----
    print("[3/6] Creating AuroraEnvironment + adding components ...")
    env = AuroraEnvironment(image_fs, container, gpu_info)

    # Add Aurora engine components (Phases 1-4)
    env.add_component(TextureEngineComponent(quality=container.aurora_texture_quality))
    env.add_component(MeshEngineComponent(lod_bias=container.aurora_mesh_lod_bias))
    env.add_component(LoaderEngineComponent(threshold=container.aurora_prefetch_threshold))
    env.add_component(ShaderEngineComponent(
        cloud_root=output_dir / "aurora_cloud_sim"
    ))
    # Phase 6: Mali sanitizer (only activates on Mali GPUs in auto mode)
    env.add_component(MaliSanitizerComponent(mode=container.aurora_mali_sanitizer))
    # Add Phase 7 stubs
    env.add_component(AudioComponent(driver=container.audioDriver,
                                     latency_ms=144))
    env.add_component(Box64LauncherComponent(
        guest_executable="/opt/witcher3/bin/witcher3.exe",
        working_dir=Path("/opt/witcher3"),
    ))
    print(f"      Added {len(env.components)} components:")
    for c in env.components:
        print(f"        - {c.name}")
    print()

    # ---- Run AOT preprocessing (game install) ----
    print("[4/6] Running AOT preprocessing (game install) ...")
    print("      This is the slow step - ~10-20 min for a real AAA game.")
    print("      For PoC, each engine runs on synthetic data.\n")

    t0 = time.perf_counter()
    for c in env.components:
        if hasattr(c, "preprocess_on_install"):
            print(f"  --- {c.name} ---")
            c.preprocess_on_install()
            print()
    install_time_s = time.perf_counter() - t0
    print(f"      Total install time: {install_time_s:.1f}s (PoC; real game = 10-20 min)")
    print()

    # ---- Build env var matrix ----
    print("[5/6] Building env var matrix for game launch ...")
    env_vars = env.build_env_vars()
    print(f"      Total env vars: {len(env_vars)}")
    print()

    # Print grouped env vars (truncated for readability)
    print("      --- Filesystem / runtime ---")
    for k in ["HOME", "USER", "TMPDIR", "DISPLAY", "PATH", "LD_LIBRARY_PATH",
              "BOX64_LD_LIBRARY_PATH", "WINEPREFIX"]:
        if k in env_vars:
            v = env_vars.get(k)
            print(f"        {k}={v[:80]}{'...' if len(v) > 80 else ''}")

    print("\n      --- Box64 tuning ---")
    for k in ["BOX64_NOBANNER", "BOX64_DYNAREC", "BOX64_X11GLX", "BOX64_MMAP32", "BOX64_RCFILE"]:
        if k in env_vars:
            print(f"        {k}={env_vars.get(k)}")
    if "BOX64_MMAP32" in env_vars:
        print(f"        (BOX64_MMAP32=0 set because GPU is Mali)")

    print("\n      --- DXVK / graphics ---")
    for k in ["DXVK_STATE_CACHE_PATH", "DXVK_GPLASYNCCACHE", "DXVK_ASYNC",
              "DXVK_CONFIG_FILE", "MESA_SHADER_CACHE_MAX_SIZE", "TU_DEBUG",
              "MESA_VK_WSI_PRESENT_MODE", "VKD3D_SHADER_MODEL"]:
        if k in env_vars:
            v = env_vars.get(k)
            print(f"        {k}={v[:80]}{'...' if len(v) > 80 else ''}")
    if "TU_DEBUG" in env_vars:
        print(f"        (TU_DEBUG=noconform set because GPU is Adreno/Turnip)")

    print("\n      --- Aurora-specific (Phases 1-4, 6) ---")
    for k, v in env_vars.items():
        if k.startswith("AURORA_"):
            print(f"        {k}={v}")

    print("\n      --- Audio ---")
    print(f"        PULSE_LATENCY_MSEC={env_vars.get('PULSE_LATENCY_MSEC')}")
    print()

    # ---- Start components (game launch) ----
    print("[6/6] Starting components (game launch) ...")
    env.start_environment_components()
    print()

    # ---- Test pause/resume ordering ----
    print("=== Testing pause/resume ordering ===")
    print("(Critical: audio must resume BEFORE game launcher; launcher pauses BEFORE audio)\n")

    print(">>> Simulating Android onPause (app going to background):")
    env.on_pause()
    print()

    print(">>> Simulating Android onResume (app returning to foreground):")
    env.on_resume()
    print()

    # ---- Stop components (game exit) ----
    print(">>> Stopping all components (game exit):")
    env.stop_environment_components()
    print()

    # ---- Summary ----
    print("=== Summary ===")
    print(f"  ImageFs: {image_fs_root}")
    print(f"  Container: {container.id} ({container.name})")
    print(f"  GPU: {gpu_info.renderer} ({gpu_info.vendor})")
    print(f"  Components: {len(env.components)}")
    print(f"  Env vars: {len(env_vars)}")
    print(f"  Mali-specific vars set: {'BOX64_MMAP32' in env_vars}")
    print(f"  Adreno-specific vars set: {'TU_DEBUG' in env_vars}")
    print(f"  Aurora-specific vars set: {sum(1 for k in env_vars if k.startswith('AURORA_'))}")
    print()

    # Save results
    result = {
        "config": {
            "gpu": gpu_info.summary(),
            "container": container.summary(),
            "image_fs": image_fs.summary(),
        },
        "install_time_s": install_time_s,
        "env_vars_count": len(env_vars),
        "env_vars": env_vars.to_dict(),
        "components": [
            {"name": c.name, "started": c.is_started}
            for c in env.components
        ],
        "mali_specific_set": "BOX64_MMAP32" in env_vars,
        "adreno_specific_set": "TU_DEBUG" in env_vars,
        "aurora_vars_count": sum(1 for k in env_vars if k.startswith("AURORA_")),
    }
    result_path = output_dir / "orchestrator_pipeline_results.json"
    result_path.write_text(json.dumps(result, indent=2))
    print(f"Results JSON: {result_path}")


def main():
    parser = argparse.ArgumentParser(description="Aurora Emulator - Phase 5 Orchestration PoC")
    parser.add_argument("--output_dir", type=Path,
                        default=PROJECT_ROOT / "tests" / "orchestrator_engine_output")
    parser.add_argument("--gpu", choices=["adreno", "mali", "immortalis"],
                        default="mali",
                        help="Which GPU to simulate (default: mali - the hard case)")
    args = parser.parse_args()
    run_poc(args.output_dir, args.gpu)


if __name__ == "__main__":
    main()
